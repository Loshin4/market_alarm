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

        def fake_request(url, params=None, data=None, timeout=30, **kwargs):
            request_values = data or params or {}
            page = int(request_values.get("pageIndex", 1))
            return FakeResponse(text=page1 if page == 1 else empty)

        # collect_kind() may use either POST or GET depending on the KIND response.
        # Unit tests must mock both methods so validation never contacts the live site.
        with patch.object(collector, "http_get", side_effect=fake_request), \
             patch.object(collector, "http_post", side_effect=fake_request):
            result = collector.collect_kind({})
        self.assertEqual(len(result.events), 2)
        titles = [e["title"] for e in result.events]
        self.assertTrue(any("SK하이닉스" in t and "실적" in t for t in titles))
        self.assertTrue(any("한미반도체" in t for t in titles))
        hanmi = next(e for e in result.events if "한미반도체" in e["title"])
        self.assertTrue(hanmi["allDay"])
        self.assertGreaterEqual(hanmi["importance"], 4)

    def test_kind_detail_page_catches_samsung_electronics(self):
        detail = """
        <table>
          <tr><th>회사명</th><td>삼성전자</td><th>시장구분</th><td>유가증권시장</td></tr>
          <tr><th>일자</th><td>2026-07-30</td><th>시간</th><td>10:00</td></tr>
          <tr><th>제목</th><td>2026년 2분기 경영실적 발표</td></tr>
          <tr><th>내용</th><td>2026년 2분기 경영실적 및 Q&amp;A</td></tr>
        </table>
        """
        item = collector.parse_kind_detail(detail, "https://kind.krx.co.kr/detail", "45065")
        self.assertIsNotNone(item)
        self.assertIn("삼성전자", item["title"])
        self.assertEqual(item["market"], "KR")
        dt = collector.datetime.fromtimestamp(item["time"] / 1000, collector.UTC).astimezone(collector.KST)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 7, 30, 10, 0))

    def test_official_ir_page_catches_samsung_electronics(self):
        html = """
        <div>2026년 2/4분기 실적발표 컨퍼런스콜</div>
        <div>일정 2026년 7월 30일 오전 10시</div>
        """
        items = collector.parse_official_ir_page(
            "삼성전자", "005930", "https://www.samsung.com/sec/ir/ir-events-presentations/events/", html
        )
        self.assertEqual(len(items), 1)
        self.assertIn("삼성전자", items[0]["title"])
        self.assertEqual(items[0]["sourceKey"], "official_ir")


    def test_official_ir_page_catches_samsung_electro_mechanics_without_registration_date(self):
        html = """
        <div>Registration Date 2026.07.09</div>
        <div>Organization of Investor Relations Event</div>
        <div>Date &amp; Time 2026-07-30 13:30</div>
        <div>Purpose of IR Q2 FY2026 Earnings release</div>
        <div>Decision Date 2026-07-09</div>
        <div>Publication Date 2026-07-30</div>
        """
        items = collector.parse_official_ir_page(
            "삼성전기", "009150",
            "https://www.samsungsem.com/global/about-us/investor-relations/disclosure/view.do?id=335",
            html,
        )
        self.assertEqual(len(items), 1)
        self.assertIn("삼성전기", items[0]["title"])
        self.assertIn("2026년 2분기", items[0]["title"])
        dt = collector.datetime.fromtimestamp(items[0]["time"] / 1000, collector.UTC).astimezone(collector.KST)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 7, 30, 13, 30))

    def test_app_removes_company_search_and_adds_calendar_counts(self):
        app = (MODULE_PATH.parents[1] / "app" / "src" / "main" / "assets" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("회사명 또는 종목코드 검색", app)
        self.assertIn('class="count"', app)
        self.assertIn('data-filter="KR"', app)
        self.assertIn('data-sort="good"', app)

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

    def test_dart_public_kind_fallback_applies_to_any_company(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("document.xml", '''
                <html><body>
                기업설명회(IR) 개최
                일시 2026-08-05 14:30
                개최목적 회사소개 및 사업현황 설명
                </body></html>
            ''')

        list_payload = {
            "status": "000", "total_page": 1,
            "list": [{
                "rcept_no": "20260709800999",
                "corp_name": "예시전기",
                "stock_code": "123456",
                "rcept_dt": "20260709",
                "report_nm": "기업설명회(IR)개최(안내공시)",
            }],
        }
        dart_main = '''
        <html><body>
          <iframe src="https://kind.krx.co.kr/external/2026/07/09/000242/20260708000898/99664.htm"></iframe>
        </body></html>
        '''
        kind_external = '''
        <html><body><table>
          <tr><th>1. 일시 및 장소</th><th>일시</th><td>2026-07-30</td><td>13:30</td></tr>
          <tr><th>3. 개최목적</th><td>2026년도 2분기 경영실적 발표</td></tr>
          <tr><th>6. 주요 설명회내용(요약)</th><td>2026년도 2분기 경영실적 및 Q&amp;A</td></tr>
          <tr><th>7. 결정일자</th><td>2026-07-09</td></tr>
        </table></body></html>
        '''

        def fake_get(url, params=None, timeout=30, **kwargs):
            if url == collector.DART_LIST:
                return FakeResponse(payload=list_payload)
            if url == collector.DART_DOCUMENT:
                return FakeResponse(content=buf.getvalue())
            if url.startswith(collector.DART_PUBLIC_VIEW):
                return FakeResponse(text=dart_main)
            if url.startswith("https://kind.krx.co.kr/external/"):
                return FakeResponse(text=kind_external)
            raise AssertionError(f"unexpected URL: {url}")

        state = {}
        with patch.object(collector, "http_get", side_effect=fake_get), \
             patch.object(collector.time, "sleep", return_value=None):
            result = collector.collect_dart_schedules("key", state, False)
        self.assertEqual(len(result.events), 1)
        item = result.events[0]
        self.assertIn("예시전기", item["title"])
        self.assertEqual(item["symbol"], "123456")
        self.assertEqual(item["confidence"], "official_krx_html")
        self.assertIn("kind.krx.co.kr/external/", item["sourceUrl"])
        dt = collector.datetime.fromtimestamp(item["time"] / 1000, collector.UTC).astimezone(collector.KST)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 7, 30, 13, 30))

    def test_settlement_results_preview_is_collected_for_any_company(self):
        sample = '''
        결산실적공시예고(안내공시)
        결산실적 공시예정일 2026-08-10
        공시예정시간 09:00
        '''
        item = collector.extract_ir_schedule_from_document(
            text=sample,
            corp_name="모든회사",
            stock_code="654321",
            receipt_no="20260726000999",
            receipt_date=collector.date(2026, 7, 26),
            report_name="결산실적공시예고(안내공시)",
        )
        self.assertIsNotNone(item)
        self.assertIn("모든회사", item["title"])
        dt = collector.datetime.fromtimestamp(item["time"] / 1000, collector.UTC).astimezone(collector.KST)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 8, 10, 9, 0))

    def test_no_company_specific_official_ir_pages_are_configured(self):
        import json
        config_path = MODULE_PATH.parents[1] / "config" / "collector.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config.get("officialIrPages"), [])

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


    def test_tentative_result_parser_extracts_market_wide_financials(self):
        html = """
        <html><body><p>(단위 : 백만원)</p><table>
          <tr><th>구분</th><th>당기실적</th><th>전기실적</th><th>전년동기실적</th></tr>
          <tr><td>매출액 당해실적</td><td>17,000,000</td><td>16,000,000</td><td>15,000,000</td></tr>
          <tr><td>영업이익 당해실적</td><td>9,000,000</td><td>8,000,000</td><td>7,000,000</td></tr>
          <tr><td>당기순이익 당해실적</td><td>6,000,000</td><td>5,000,000</td><td>4,000,000</td></tr>
        </table></body></html>
        """
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("document.xml", html)
        item = collector.parse_tentative_result_document(
            buf.getvalue(), corp_name="어떤회사", stock_code="123456",
            receipt_no="20260726000003", receipt_date=collector.date(2026, 7, 26),
            report="영업(잠정)실적(공정공시)",
        )
        self.assertIn("매출", item["summary"])
        self.assertIn("영업익", item["summary"])
        self.assertEqual(item["market"], "KR")
        self.assertEqual(item["status"], "released")
        self.assertGreater(item["rating"], 0)

    def test_sec_companyfacts_extracts_revenue_operating_and_previous(self):
        payload = {
            "facts": {"us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                    {"start": "2025-04-01", "end": "2025-06-30", "filed": "2025-07-25", "form": "10-Q", "val": 10000000000, "accn": "0001-25-000001"},
                    {"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-07-26", "form": "10-Q", "val": 12000000000, "accn": "0001-26-000001"},
                ]}},
                "OperatingIncomeLoss": {"units": {"USD": [
                    {"start": "2025-04-01", "end": "2025-06-30", "filed": "2025-07-25", "form": "10-Q", "val": 1000000000, "accn": "0001-25-000001"},
                    {"start": "2026-04-01", "end": "2026-06-30", "filed": "2026-07-26", "form": "10-Q", "val": 1500000000, "accn": "0001-26-000001"},
                ]}},
            }}
        }
        result = collector.extract_sec_company_result(payload, collector.date(2026, 7, 26))
        self.assertEqual(result["revenue"], 12000000000)
        self.assertEqual(result["revenue_previous"], 10000000000)
        self.assertEqual(result["operating"], 1500000000)


if __name__ == "__main__":
    unittest.main()
