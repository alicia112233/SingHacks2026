from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest

from tessera.engine import build_intelligence_payload, load_dataset
from tessera.risk_analysis import DEFAULT_THRESHOLDS, analyse_client, band, order_by_urgency

ROOT = Path(__file__).resolve().parents[1]


class RiskAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset(ROOT / 'data')
        cls.as_of = str(cls.bundle['holdings'].snapshot_date.max())
        cls.payload = build_intelligence_payload(ROOT / 'data')

    def test_supplied_customers_and_unchanged_urgency(self):
        expected = {'CL-0014':79,'CL-0011':69,'CL-0017':64,'CL-0003':61,'CL-0012':53,'CL-0016':53,'CL-0006':47,'CL-0019':46,'CL-0018':42,'CL-0001':36,'CL-0005':36,'CL-0002':31,'CL-0020':29,'CL-0009':25,'CL-0004':20,'CL-0008':20,'CL-0007':15,'CL-0013':15,'CL-0010':10,'CL-0015':10}
        queue = self.payload['book']['priority_queue']
        self.assertEqual({c['client_id']:c['score'] for c in queue}, expected)
        for client in self.payload['client_profiles'].values():
            risk = client['risk_analysis']
            self.assertTrue(all(1 <= risk[k] <= 5 for k in ('capacity','tolerance','horizon')))
            self.assertAlmostEqual(risk['overall'], (risk['capacity'] + risk['tolerance'] + risk['horizon']) / 3)
        self.assertEqual([(c['score'],c['risk_analysis']['overall']) for c in queue], sorted([(c['score'],c['risk_analysis']['overall']) for c in queue],key=lambda x:(-x[0],x[1])))

    def test_tolerance_and_horizon_boundaries(self):
        for raw, expected in [(1,1),(2,1),(3,2),(4,2),(5,3),(6,3),(7,4),(8,4),(9,5),(10,5)]:
            self.assertEqual(band(raw,DEFAULT_THRESHOLDS.tolerance),expected)
        for years, expected in [(0,1),(1,1),(1.01,2),(3,2),(3.01,3),(5,3),(5.01,4),(10,4),(10.01,5)]:
            self.assertEqual(band(years,DEFAULT_THRESHOLDS.horizon_years),expected)
        self.assertEqual(band(0.03, DEFAULT_THRESHOLDS.cash_share),2)
        self.assertEqual(band(0.0301, DEFAULT_THRESHOLDS.cash_share),3)
        self.assertEqual(band(0.8, DEFAULT_THRESHOLDS.daily_liquid_share),4)

    def test_capacity_uses_available_holdings_and_recorded_debt(self):
        import pandas as pd
        client = SimpleNamespace(client_id='TEST',risk_tolerance_score=6,investment_horizon_years=5)
        bundle = {'holdings':pd.DataFrame([{'client_id':'TEST','snapshot_date':self.as_of,'market_value_usd':10,'asset_class':'Cash and Equivalents','liquidity_tier':'Daily'}, {'client_id':'TEST','snapshot_date':self.as_of,'market_value_usd':90,'asset_class':'Equity','liquidity_tier':'Illiquid'}]), 'credit_facilities':pd.DataFrame(columns=['client_id'])}
        self.assertEqual(analyse_client(bundle,client,self.as_of)['capacity'],2.5)  # cash 4, daily liquidity 1
        bundle['credit_facilities']=pd.DataFrame([{'client_id':'TEST',f'ltv_pct_{self.as_of}':69,'margin_call_ltv_pct':75}])
        self.assertEqual(analyse_client(bundle,client,self.as_of)['capacity'],2)  # debt at 92% scores 1
        risk=analyse_client(bundle,client,self.as_of,replace(DEFAULT_THRESHOLDS,cash_share=(0.2,0.3,0.4,0.5)))
        self.assertEqual(risk['capacity'],1)

    def test_missing_dimensions_are_not_invented(self):
        bundle = {k:v.copy() if hasattr(v,'copy') else v for k,v in self.bundle.items()}
        client = SimpleNamespace(client_id='MISSING',risk_tolerance_score=None,investment_horizon_years=None)
        risk = analyse_client(bundle,client,self.as_of)
        self.assertTrue(all(risk[k] is None for k in ('capacity','tolerance','horizon','overall')))
        self.assertIn('Insufficient data',risk['explanation'])
        client.risk_tolerance_score = 11
        self.assertIsNone(analyse_client(bundle,client,self.as_of)['tolerance'])

    def test_holdings_never_determine_tolerance_and_goal_date_fallback(self):
        client = SimpleNamespace(client_id='CL-0003',risk_tolerance_score=2,investment_horizon_years=None)
        risk = analyse_client(self.bundle,client,self.as_of)
        self.assertEqual(risk['tolerance'],1)
        self.assertEqual(risk['horizon'],1)
        self.assertIn('2026-10-01',risk['explanation'])
        client.risk_tolerance_score=None
        self.assertIsNone(analyse_client(self.bundle,client,self.as_of)['overall'])

    @staticmethod
    def customer(name, urgency, risk):
        return {'client_id':name,'score':urgency,'risk_analysis':{'overall':risk}}

    def test_requested_ordering_example(self):
        a,b,c = self.customer('A',80,2),self.customer('B',80,4),self.customer('C',70,1)
        self.assertEqual(order_by_urgency([b,c,a]),[a,b,c])

    def test_incomplete_tied_group_keeps_entire_existing_order(self):
        a,b,c,d = self.customer('A',80,4),self.customer('B',80,None),self.customer('C',80,1),self.customer('D',70,1)
        self.assertEqual(order_by_urgency([d,a,b,c]),[a,b,c,d])
        del b['risk_analysis']
        self.assertEqual(order_by_urgency([a,b,c,d]),[a,b,c,d])

    def test_identical_risk_scores_stay_stable(self):
        a,b = self.customer('A',80,2),self.customer('B',80,2)
        self.assertEqual(order_by_urgency([b,a]),[b,a])


if __name__ == '__main__':
    unittest.main()
