"""Offline, source-backed chatbot evaluation with explicit per-check denominators."""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tessera.chat import INSUFFICIENT_ANSWER, _model_answer, answer_chat, retrieve_chat_evidence
from tessera.source_policy import content_hash


def evaluate_database_records(data_dir: Path) -> tuple[list[dict], dict[str, str]]:
    """Reconcile answers against raw CSV values independently of engine calculations."""

    from tessera.engine import build_intelligence_payload

    holdings_path = data_dir / "holdings.csv"
    credit_path = data_dir / "credit_facilities.csv"
    with holdings_path.open(encoding="utf-8-sig", newline="") as handle:
        holdings = list(csv.DictReader(handle))
    with credit_path.open(encoding="utf-8-sig", newline="") as handle:
        facilities = list(csv.DictReader(handle))
    latest = max(row["snapshot_date"] for row in holdings)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for row in holdings:
        if row["snapshot_date"] == latest:
            totals[row["client_id"]] += Decimal(row["market_value_usd"])
    checks = []
    with mock.patch.dict("os.environ", {}, clear=True):
        intelligence = build_intelligence_payload(data_dir)
        for client_id, total in sorted(totals.items()):
            answer = answer_chat(intelligence, {"client_id": client_id, "question": "What is the bank-held AUM?"})
            match = re.search(r"AUM is USD ([0-9.]+)m", answer["answer"])
            # AUM is displayed to two decimal places in millions: at most USD 5,000 rounding.
            passed = bool(match) and abs(Decimal(match[1]) * 1_000_000 - total) <= Decimal("5000")
            passed = passed and latest in answer["answer"] and any(
                item["source_id"] == "portfolio" and client_id in item["source"] for item in answer["citations"]
            )
            checks.append({"id": f"csv-aum-{client_id}", "metric": "csv_aum_reconciliation", "passed": bool(passed),
                           "expected_usd": str(total), "snapshot_date": latest})
        for facility in facilities:
            client_id = facility["client_id"]
            if sum(row["client_id"] == client_id for row in facilities) != 1:
                continue
            answer = answer_chat(intelligence, {"client_id": client_id, "question": "What are the credit LTV and trigger?"})
            ltv = re.search(r"LTV ([0-9.]+)%", answer["answer"])
            trigger = re.search(r"against a ([0-9.]+)% trigger", answer["answer"])
            passed = bool(ltv and trigger) and (
                Decimal(ltv[1]) == Decimal(facility[f"ltv_pct_{latest}"])
                and Decimal(trigger[1]) == Decimal(facility["margin_call_ltv_pct"])
            )
            checks.append({"id": f"csv-credit-{facility['facility_id']}", "metric": "csv_credit_reconciliation", "passed": bool(passed)})
    hashes = {path.name: content_hash(path.read_text(encoding="utf-8-sig")) for path in sorted(data_dir.iterdir())
              if path.suffix in {".csv", ".json"}}
    return checks, hashes


def evaluate_chat(fixture_path: Path, data_dir: Path | None = None) -> dict:
    fixture_bytes = fixture_path.read_text(encoding="utf-8")
    fixture = json.loads(fixture_bytes)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    results = []

    def check(metric: str, passed: bool) -> bool:
        counts[metric][0] += int(passed)
        counts[metric][1] += 1
        return passed

    # Never load .env.local, fetch feeds, embed text, or spend inference credits.
    with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
        "tessera.chat.urlopen", side_effect=AssertionError("Evaluation must not use the network")
    ), mock.patch("tessera.retrieval.urlopen", side_effect=AssertionError("Evaluation must not use the network")):
        for case in fixture["cases"]:
            intelligence = copy.deepcopy(fixture["intelligence"])
            client_id = case.get("client_id", "CL-9001")
            client = intelligence["client_profiles"][client_id]
            if case.get("remove_field"):
                client.pop(case["remove_field"], None)
            evidence, _ = retrieve_chat_evidence(client, case["question"])
            answer = answer_chat(intelligence, {
                "client_id": client_id, "question": case["question"], "history": case.get("history", []),
            })
            checks = {}
            abstain = case.get("abstain", False)
            actual_abstention = answer["mode"] == "insufficient_evidence"
            checks["answerability"] = check("answerability", actual_abstention == abstain)
            if abstain:
                checks["abstention"] = check("unanswerable_refusal", actual_abstention and not answer["citations"])
            else:
                expected_sources = set(case["sources"])
                checks["retrieval"] = check("primary_source_recall_at_6", case["sources"][0] in {item["id"] for item in evidence})
                checks["answer_key"] = check("answer_key_match", all(value in answer["answer"] for value in case.get("contains", [])))
                if case["category"] == "numerical":
                    checks["numerical"] = check("numerical_answer_key_match", checks["answer_key"])
                checks["citations"] = bool(answer["citations"])
                for citation in answer["citations"]:
                    checks["citations"] &= check("citation_source_precision", citation["source_id"] in expected_sources)
                    checks["extract_fidelity"] = check("extract_fidelity", (
                        f"{citation['excerpt']} [{citation['number']}]" in answer["answer"]
                        and citation["content_sha256"] == content_hash(citation["excerpt"])
                    )) and checks.get("extract_fidelity", True)
                if case.get("publisher"):
                    checks["news_provenance"] = check("news_provenance", any(
                        citation["publisher"] == case["publisher"]
                        and citation["source_url"] == case["source_url"]
                        and citation["published_at"] and citation["retrieved_at"]
                        and citation["evidence_kind"] == "external_report"
                        and citation["verification_status"] == "external_report_not_verified"
                        for citation in answer["citations"]
                    ))
            checks["excluded_values"] = check("excluded_value_safety", all(value not in answer["answer"] for value in case.get("excludes", [])))
            if case["category"] == "isolation":
                checks["isolation"] = check("client_isolation", (
                    "77.0" not in answer["answer"] and "Beta" not in answer["answer"]
                    and all("CL-9002" not in item["source"] for item in answer["citations"])
                ))
            results.append({"id": case["id"], "category": case["category"], "passed": all(checks.values()),
                            "checks": checks, "mode": answer["mode"], "answer": answer["answer"], "citations": answer["citations"]})

    # Exercise the real gateway-response parser with hostile simulated completions.
    # These are contract tests, not a live-model quality measurement.
    evidence = [{"citation": 1, "source": "holdings.csv", "excerpt": "Bank-held AUM is USD 20m."}]
    completions = [
        ("fabricated_valid_citation", "AUM is USD 999m [1].", False),
        ("extra_answer_field", '{"citations":[1],"insufficient":false,"answer":"USD 999m"}', False),
        ("unknown_citation", '{"citations":[99],"insufficient":false}', False),
        ("negative_citation", '{"citations":[-1],"insufficient":false}', False),
        ("boolean_citation", '{"citations":[true],"insufficient":false}', False),
        ("duplicate_citation", '{"citations":[1,1],"insufficient":false}', False),
        ("valid_selection", '{"citations":[1],"insufficient":false}', True),
        ("valid_abstention", '{"citations":[],"insufficient":true}', True),
    ]
    contract_results = []
    for name, completion, expected_accept in completions:
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_args): self.close()
        response = Response(json.dumps({"choices": [{"message": {"content": completion}}]}).encode())
        accepted = False
        output = ""
        try:
            with mock.patch("tessera.chat.urlopen", return_value=response):
                output = _model_answer("What is the AUM?", evidence, [], "test-only")
                accepted = True
        except ValueError:
            pass
        passed = accepted == expected_accept and (
            not accepted or output == INSUFFICIENT_ANSWER or output.endswith("Bank-held AUM is USD 20m. [1]")
        )
        check("simulated_model_contract", passed)
        contract_results.append({"id": name, "passed": passed})

    database_checks, dataset_hashes = evaluate_database_records(data_dir or fixture_path.parent.parent / "data")
    for row in database_checks:
        check(row["metric"], row["passed"])

    implementation = "".join((Path(__file__).parent / name).read_text(encoding="utf-8")
                             for name in ("chat.py", "retrieval.py", "source_policy.py", "chat_evaluation.py", "engine.py", "market_news.py"))
    return {
        "suite_version": fixture["version"], "fixture_sha256": content_hash(fixture_bytes),
        "implementation_sha256": content_hash(implementation),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution": "offline_extracts_and_simulated_gateway_contracts",
        "live_model_evaluated": False, "independent_source_truth_verified": False,
        "passed": all(row["passed"] for row in results + contract_results + database_checks),
        "metrics": {key: {"passed": value[0], "total": value[1], "rate": value[0] / value[1]}
                    for key, value in sorted(counts.items())},
        "cases": results, "simulated_model_contracts": contract_results,
        "database_checks": database_checks, "source_file_sha256": dataset_hashes,
    }


def evaluation_markdown(report: dict) -> str:
    rows = ["# Chatbot evaluation results", "", f"Suite: `{report['suite_version']}`",
            f"Generated: {report['generated_at']}", f"Overall: {'PASS' if report['passed'] else 'FAIL'}", "",
            "Offline source extracts and simulated gateway response contracts. No live model or live news was evaluated; source truth was not independently verified.", "",
            "| Check | Passed | Total | Rate |", "| --- | ---: | ---: | ---: |"]
    rows += [f"| {name} | {value['passed']} | {value['total']} | {value['rate']:.1%} |"
             for name, value in report["metrics"].items()]
    rows += ["", "## Cases", "", "| Case | Category | Result |", "| --- | --- | --- |"]
    rows += [f"| {row['id']} | {row['category']} | {'PASS' if row['passed'] else 'FAIL'} |" for row in report["cases"]]
    rows += ["", "## Database reconciliation", "",
             "Answers are compared with independent CSV reads: latest-snapshot USD holdings totals for every client, and recorded LTV/trigger fields for clients with a single credit facility. AUM uses a USD 5,000 tolerance because the application displays millions to two decimal places.", "",
             "| Check | Result |", "| --- | --- |"]
    rows += [f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} |" for row in report["database_checks"]]
    rows += ["", "## Reproducibility", "", f"Fixture SHA-256: `{report['fixture_sha256']}`",
             f"Implementation SHA-256: `{report['implementation_sha256']}`", "",
             "Run `python scripts/evaluate_chat.py --report docs/CHAT_EVALUATION_RESULTS.md` from the application directory.", "",
             "Recall checks the manually labelled primary source in the first six passages. Citation precision checks source IDs against the answer key. Extract fidelity measures verbatim passage reproduction and hashes, not independent factual correctness. Numerical checks use explicit expected amounts, units and dates. The small synthetic suite is a regression gate, not a production error-rate estimate.", ""]
    rows += ["Source file fingerprints are included in the JSON companion report.", ""]
    return "\n".join(rows)