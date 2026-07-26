import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("collect_events.py")
spec = importlib.util.spec_from_file_location("collect_events", MODULE_PATH)
collector = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is not None:
            return self._payload
        raise AssertionError("JSON not configured")


class CollectorTests(unittest.TestCase):
    def test_alpha_calendar_collects_all_companies_without_watchlist(self):
        csv_text = """symbol,name,reportDate,fiscalDateEnding,estimate,currency,country,reportTime
INTC,Intel Corporation,2026-08-01,2026-06-30,0.25,USD,United States,after market close
SNDK,SanDisk Corporation,2026-08-02,2026-06-30,1.10,USD,United States,after market close
ZZZZ,Example Small Company,2026-08-03,2026-06-30,,USD,United States,
"""
        state = {}
        with tempfile.TemporaryDirectory() as td:
            old_file = collector.EVENTS_FILE
            collector.EVENTS_FILE = Path(td) / "events.json"
            collector.EVENTS_FILE.write_text('{"events": []}', encoding="utf-8")
            try:
                with patch.object(collector, "http_get", return_value=FakeResponse(text=csv_text)):
                    result = collector.collect_alpha({}, "key", state, False)
            finally:
                collector.EVENTS_FILE = old_file
        scheduled = [e for e in result.events if e["status"] == "scheduled"]
        self.assertEqual({e["symbol"] for e in scheduled}, {"INTC", "SNDK", "ZZZZ"})
        titles = {e["symbol"]: e["title"] for e in scheduled}
        self.assertIn("인텔(INTC)", titles["INTC"])
        self.assertIn("샌디스크(SNDK)", titles["SNDK"])
        self.assertEqual(titles["ZZZZ"], "ZZZZ 실적 발표")

    def test_kind_collects_all_pages_and_deduplicates_english_copy(self):
        page1 = """
        <table><tbody>
          <tr><td>4</td><td>유가증권 삼성전자</td><td>2026년 2분기 경영실적 발표</td><td>-</td><td>2026-07-30</td><td>10:00</td></tr>
          <tr><td>3</td><td>유가증권 SK하이닉스</td><td>2026년 2분기 경영실적 발표</td><td>-</td><td>2026-07-29</td><td>09:00</td></tr>
        </tbody></table><div>전체 4건 : 1/2</div>
        """
        page2 = """
        <table><tbody>
          <tr><td>2</td><td>유가증권 SK하이닉스</td><td>Earnings Release on Second Quarter of 2026</td><td>-</td><td>2026-07-29</td><td>09:00</td></tr>
          <tr><td>1</td><td>코스닥 한미반도체</td><td>2026년 2분기 실적설명회</td><td>-</td><td>2026-07-30</td><td>--:--</td></tr>
        </tbody></table><div>전체 4건 : 2/2</div>
        """

        with patch.object(collector, "fetch_kind_page", side_effect=[page1, page2]):
            result = collector.collect_kind({})
        self.assertEqual(len(result.events), 3)
        titles = [e["title"] for e in result.events]
        self.assertTrue(any("삼성전자" in t for t in titles))
        self.assertTrue(any("SK하이닉스" in t and "경영실적" in t for t in titles))
        self.assertTrue(any("한미반도체" in t for t in titles))
        hanmi = next(e for e in result.events if "한미반도체" in e["title"])
        self.assertTrue(hanmi["allDay"])
        self.assertGreaterEqual(hanmi["importance"], 4)

    def test_kind_event_id_survives_time_change(self):
        d1 = collector.parse_kind_page("""
        <table><tbody><tr><td>1</td><td>유가증권 SK하이닉스</td><td>2026년 2분기 경영실적 발표</td><td>-</td><td>2026-07-29</td><td>09:00</td></tr></tbody></table>
        """, 1)[0][0]
        d2 = collector.parse_kind_page("""
        <table><tbody><tr><td>1</td><td>유가증권 SK하이닉스</td><td>2026년 2분기 경영실적 발표</td><td>-</td><td>2026-07-30</td><td>10:00</td></tr></tbody></table>
        """, 1)[0][0]
        self.assertEqual(d1["id"], d2["id"])
        self.assertNotEqual(d1["time"], d2["time"])


    def test_future_kind_event_is_not_deleted_after_one_partial_snapshot(self):
        old = {
            "id": "kr-earnings-test-2026-Q2",
            "title": "SK하이닉스 2026년 2분기 경영실적 발표",
            "time": collector.NOW_MS + 3 * 24 * 60 * 60 * 1000,
            "status": "scheduled",
            "sourceKey": "kind",
            "importance": 5,
        }
        state = {}
        merged = collector.merge_events([], [old], set(), {"kind"}, state)
        self.assertEqual(len(merged), 1)
        self.assertEqual(state["missingScheduledCounts"][old["id"]], 1)

    def test_collector_changes_do_not_trigger_apk_build(self):
        workflow = (MODULE_PATH.parents[1] / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
        self.assertIn('paths:', workflow)
        self.assertIn('- "app/**"', workflow)
        self.assertNotIn('collector/**', workflow)


if __name__ == "__main__":
    unittest.main()
