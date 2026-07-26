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
    def __init__(self, text="", payload=None, content=None):
        self.text = text
        self._payload = payload
        self.content = content if content is not None else text.encode("utf-8")

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

    def test_kind_collects_all_earnings_and_deduplicates_english_copy(self):
        page1 = """
        <table><tbody>
          <tr><td>3</td><td>유가증권 SK하이닉스</td><td>2026년 2분기 경영실적 발표</td><td>-</td><td>2026-07-29</td><td>09:00</td></tr>
          <tr><td>2</td><td>유가증권 SK하이닉스</td><td>Earnings Release on Second Quarter of 2026</td><td>-</td><td>2026-07-29</td><td>09:00</td></tr>
          <tr><td>1</td><td>코스닥 한미반도체</td><td>2026년 2분기 실적설명회</td><td>-</td><td>2026-07-30</td><td>--:--</td></tr>
        </tbody></table>
        """
        empty = "<table><tbody></tbody></table>"

        def fake_get(url, params=None, timeout=30):
            page = int((params or {}).get("pageIndex", 1))
            return FakeResponse(text=page1 if page == 1 else empty)

        with patch.object(collector, "http_get", side_effect=fake_get):
            result = collector.collect_kind({})
        self.assertEqual(len(result.events), 2)
        titles = [e["title"] for e in result.events]
        self.assertTrue(any("SK하이닉스" in t and "경영실적" in t for t in titles))
        self.assertTrue(any("한미반도체" in t for t in titles))
        hanmi = next(e for e in result.events if "한미반도체" in e["title"])
        self.assertTrue(hanmi["allDay"])
        self.assertGreaterEqual(hanmi["importance"], 4)

    def test_dart_ir_parser_accepts_any_company_without_allowlist(self):
        sample = """
        기업설명회(IR) 개최(안내공시)
        1. 일시 및 장소 일시 2026-08-05 14:30 장소 온라인
        2. 참가 대상자 국내외 투자자
        3. 개최목적 2026년 2분기 경영실적 발표
        4. 개최방법 Conference Call
        5. 주요 설명회내용(요약) 2026년 2분기 경영실적 및 질의응답
        7. 결정일자 2026-07-26
        """
        item = collector.extract_ir_schedule_from_document(
            text=sample,
            corp_name="예시테크",
            stock_code="123456",
            receipt_no="20260726000001",
            receipt_date=collector.date(2026, 7, 26),
        )
        self.assertIsNotNone(item)
        self.assertIn("예시테크", item["title"])
        self.assertEqual(item["symbol"], "123456")
        self.assertEqual(item["market"], "KR")
        self.assertEqual(item["sourceKey"], "dart_schedule")
        dt = collector.datetime.fromtimestamp(item["time"] / 1000, collector.UTC).astimezone(collector.KST)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 8, 5, 14, 30))

    def test_non_earnings_ir_is_excluded(self):
        sample = """
        기업설명회(IR) 개최
        일시 2026-08-05 14:30
        개최목적 회사소개 및 사업현황 설명
        주요 설명회내용 신규 사업 소개
        """
        item = collector.extract_ir_schedule_from_document(
            text=sample,
            corp_name="예시기업",
            stock_code="654321",
            receipt_no="20260726000002",
            receipt_date=collector.date(2026, 7, 26),
        )
        self.assertIsNone(item)

    def test_merge_preserves_future_korean_schedule_when_one_run_misses_it(self):
        old = collector.event(
            event_id="kr-earnings-old-2026-08-01",
            title="예시기업 2026년 2분기 실적 발표",
            when=collector.datetime(2026, 8, 1, 9, 0, tzinfo=collector.KST),
            source_key="dart_schedule",
            source="공식",
            source_url="https://example.com",
            category="earnings",
            importance=3,
            market="KR",
        )
        merged = collector.merge_events([], [old], set())
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["confidence"], "previous_official_schedule")

    def test_nasdaq_collects_market_wide_rows(self):
        payload = {
            "data": {
                "rows": [
                    {"symbol": "INTC", "name": "Intel Corporation", "time": "time-after-hours", "epsForecast": "0.25", "fiscalQuarterEnding": "Jun/2026"},
                    {"symbol": "SNDK", "name": "SanDisk Corporation", "time": "time-not-supplied", "epsForecast": "1.10", "fiscalQuarterEnding": "Jun/2026"},
                    {"symbol": "SMALL", "name": "Small Company", "time": "time-pre-market", "epsForecast": "", "fiscalQuarterEnding": "Jun/2026"},
                ]
            }
        }
        state = {}
        with patch.object(collector, "http_get", return_value=FakeResponse(payload=payload)):
            with patch.object(collector.time, "sleep", return_value=None):
                result = collector.collect_nasdaq_earnings(state, True)
        symbols = {e["symbol"] for e in result.events}
        self.assertEqual(symbols, {"INTC", "SNDK", "SMALL"})

    def test_data_changes_do_not_trigger_apk_build(self):
        workflow = (MODULE_PATH.parents[1] / ".github" / "workflows" / "build-apk.yml").read_text(encoding="utf-8")
        self.assertIn('paths-ignore:', workflow)
        self.assertIn('- "data/**"', workflow)


if __name__ == "__main__":
    unittest.main()
