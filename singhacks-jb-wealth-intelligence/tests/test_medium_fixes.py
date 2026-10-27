"""Regression coverage for missing data, timing and asynchronous review state."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from xml.etree.ElementTree import Element, SubElement

import pandas as pd
from tessera.engine import build_intelligence_payload, load_dataset, _recommendation_risk_validation, _to_usd
from tessera.market_news import _approved_event
from tessera.notifications import TelegramNotificationError
from tessera.services import DecisionStore
from tessera.chat import _model_answer

ROOT = Path(__file__).resolve().parents[1]


class MediumFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset(ROOT / "data")
        cls.payload = build_intelligence_payload(ROOT / "data")

    def test_missing_profile_values_cannot_pass_the_gate(self):
        profile = self.payload["client_profiles"]["CL-0011"]
        for value in (float("nan"), pd.NA, None, "   ", "nan"):
            for field in ("objectives", "risk_profile"):
                bundle = deepcopy(self.bundle)
                bundle["clients"].loc[bundle["clients"].client_id == "CL-0011", field] = value
                validation = _recommendation_risk_validation(bundle, profile, profile["recommendations"][1])
                self.assertEqual(validation["score"], 0, (value, field))
                self.assertIn("Client objective or risk profile is missing", validation["blockers"])

    def test_missing_csv_profile_fields_still_produce_valid_blocked_json(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            shutil.copytree(ROOT / "data", data)
            clients = pd.read_csv(data / "clients.csv")
            clients.loc[clients.client_id == "CL-0011", ["objectives", "risk_profile"]] = None
            clients.to_csv(data / "clients.csv", index=False)
            payload = build_intelligence_payload(data)
        json.dumps(payload, allow_nan=False)
        self.assertTrue(all(a["risk_validation"]["score"] == 0 for a in payload["client_profiles"]["CL-0011"]["recommendations"]))

    def test_fx_never_treats_unknown_currency_or_bad_rates_as_usd(self):
        with mock.patch("tessera.engine._market_value", return_value=2):
            self.assertEqual(_to_usd({}, 5, "SGD", "2026-08-26"), 2.5)
            self.assertEqual(_to_usd({}, 5, "EUR", "2026-08-26"), 10)
            with self.assertRaisesRegex(ValueError, "No supported USD conversion"):
                _to_usd({}, 5, "XYZ", "2026-08-26")
        for rate in (0, -1, float("nan"), float("inf")):
            with mock.patch("tessera.engine._market_value", return_value=rate), self.assertRaises(ValueError):
                _to_usd({}, 5, "SGD", "2026-08-26")

    def test_follow_up_deadlines_preserve_exact_hours_and_timezone(self):
        anchor = datetime.fromisoformat(self.payload["meta"]["as_of"]).replace(tzinfo=timezone(timedelta(hours=8)))
        for item in self.payload["book"]["priority_queue"]:
            score = item["score"]
            expected = 2 + score % 5 if score >= 70 else 14 + score % 10 if score >= 55 else 26 + score % 21 if score >= 45 else None
            if expected is None:
                self.assertEqual(item["deadline"]["date"], "")
            else:
                due = datetime.fromisoformat(item["deadline"]["date"])
                self.assertEqual(due.utcoffset(), timedelta(hours=8))
                self.assertEqual((due - anchor).total_seconds(), expected * 3600)

    def test_awards_does_not_mean_war(self):
        for title, expected in (("Equity market awards celebrate earnings", "Medium"), ("Equity market war escalates", "Severe")):
            item = Element("item")
            SubElement(item, "title").text = title
            self.assertEqual(_approved_event(item)["severity"], expected)

    def test_rss_html_attributes_do_not_become_market_claims(self):
        item = Element("item")
        SubElement(item, "title").text = "Equity market awards"
        SubElement(item, "description").text = '<a href="https://example.test/war">Equity market awards</a>'
        self.assertEqual(_approved_event(item)["severity"], "Medium")

    def test_chat_rejects_zero_negative_and_absent_citation_ids(self):
        evidence = [{"citation": 1, "source": "test", "excerpt": "Controlled fact"}]
        for citation in ("[0]", "[-1]", "[2]", "[1] plus [0]"):
            response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "A fact " + citation}}]}).encode())
            with mock.patch("tessera.chat.urlopen", return_value=response), self.assertRaisesRegex(ValueError, "citations"):
                _model_answer("Question", evidence, [], "test")
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "A fact [1]"}}]}).encode())
        with mock.patch("tessera.chat.urlopen", return_value=response):
            self.assertEqual(_model_answer("Question", evidence, [], "test"), "A fact [1]")

    def test_notification_outage_does_not_undo_hosted_news_refresh(self):
        import api.index as api
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(api.INTELLIGENCE, "get", return_value=self.payload), mock.patch.object(api, "decision_store", return_value=DecisionStore(Path(directory) / "decisions.json")), mock.patch.object(api, "urgency_alert_store", return_value=object()), mock.patch("tessera.services.refresh_market_news", return_value={"status": "refreshed", "added": 1}), mock.patch("tessera.services.scan_urgency_alerts", side_effect=TelegramNotificationError("offline")), self.assertLogs("tessera.services", level="WARNING"):
            response = api.app.test_client().post("/api/market-news/refresh", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["added"], 1)
        self.assertIn("intelligence", response.json)
        self.assertEqual(response.json["urgency_alerts"]["status"], "unavailable")

    def test_browser_clock_retries_and_out_of_order_reads(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context=vm.createContext({console,window:{setTimeout:fn=>fn()}});
vm.runInContext(fs.readFileSync('web/app.js','utf8').replace(/init\(\);\s*$/, ''),context);
(async()=>{
 assert.equal(vm.runInContext("followUpInfo({score:50,deadline:{date:'2026-10-19T10:00:00+08:00'}}).short",context),'This week');
 assert.equal(vm.runInContext("followUpInfo({score:40,escalation:{id:'x'}}).key",context),'breach');
 assert.equal(vm.runInContext("followUpInfo({score:72,escalation:{id:'x',review:{status:'dismissed'}}}).key",context),'now');
 assert.equal(vm.runInContext("followUpInfo({score:40,escalation:{id:'x',review:{status:'confirmed'}}}).short",context),'Exposure confirmed');
 assert(!vm.runInContext("fullDate('2026-10-19T12:00:00+08:00')",context).includes('INVALID'));
 vm.runInContext("state.decisions={records:[{action:'escalation_dismissed',headline:'HK property softens',reason:'Margin cushion breached',client_name:'Lau Chi Ming',recorded_at:'2026-10-20T00:00:00Z'}]}",context);
 const ledger=vm.runInContext("renderDecisionLedger()",context);
 assert(ledger.includes('Exposure dismissed')&&ledger.includes('Possible exposure: HK property softens')&&!ledger.includes('escalation_dismissed<'));
 let calls=0;
 context.fetch=async()=>{calls++;return {ok:false,status:400,json:async()=>({error:'Bad input'})}};
 await assert.rejects(vm.runInContext("requestJson('/api/review')",context),/Bad input/);assert.equal(calls,1);
 calls=0;context.fetch=async()=>{calls++;return {ok:false,status:503,json:async()=>({})}};
 await assert.rejects(vm.runInContext("requestJson('/api/notifications/urgency/acknowledge',{method:'POST'})",context));assert.equal(calls,1);
 calls=0;context.fetch=async()=>{calls++;return {ok:calls===2,status:calls===2?200:503,json:async()=>({})}};
 await vm.runInContext("requestJson('/api/review')",context);assert.equal(calls,2);
 const pending=[];context.fetch=()=>new Promise(resolve=>pending.push(resolve));
 const first=vm.runInContext('loadReviewState()',context),second=vm.runInContext('loadReviewState()',context);
 pending[1]({ok:true,json:async()=>({intelligence:{revision:2},decisions:{revision:2}})});await second;
 pending[0]({ok:true,json:async()=>({intelligence:{revision:1},decisions:{revision:1}})});assert.equal(await first,false);
 assert.equal(vm.runInContext('state.data.revision',context),2);assert.equal(vm.runInContext('state.decisions.revision',context),2);
 console.log('PASS: queue lanes, safe retries and out-of-order reads');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
