"""Run the versioned chatbot evaluation without credentials or network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tessera.chat_evaluation import evaluate_chat, evaluation_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "evals" / "chat_grounding.v1.json")
    parser.add_argument("--report", type=Path, default=ROOT / "runtime" / "chat-evaluation.md")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--cloud", action="store_true", help="Also save both reports to the cloud backend output store.")
    args = parser.parse_args()
    report = evaluate_chat(args.fixture, args.data_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(evaluation_markdown(report), encoding="utf-8")
    json_path = args.report.with_suffix(".json")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if args.cloud:
        from app import load_local_environment
        from tessera.cloud_outputs import production_output_store
        load_local_environment()
        outputs = production_output_store()
        outputs.upload_file("evaluations/chat-evaluation.md", args.report)
        outputs.upload_file("evaluations/chat-evaluation.json", json_path)
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {len(report['cases'])} questions; {len(report['simulated_model_contracts'])} simulated model contracts")
    for name, metric in report["metrics"].items():
        print(f"  {name}: {metric['passed']}/{metric['total']}")
    for case in report["cases"]:
        if not case["passed"]:
            print(f"  FAILED {case['id']}: {case['checks']}")
    for row in report["database_checks"]:
        if not row["passed"]:
            print(f"  FAILED {row['id']}")
    print(f"Report: {args.report}")
    print(f"Details: {json_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
