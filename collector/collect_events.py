#!/usr/bin/env python3
"""Market Alarm data collector.

Collects official/free market schedules and result updates, then writes JSON files
consumed by the Android app. API keys are optional GitHub Actions secrets.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_FILE = ROOT / "config" / "collector.json"
EVENTS_FILE = DATA_DIR / "events.json"
STATUS_FILE = DATA_DIR / "status.json"
CHANGES_FILE = DATA_DIR / "changes.json"
STATE_FILE = DATA_DIR / "state.json"

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
UTC = timezone.utc
NOW = datetime.now(UTC)
NOW_MS = int(NOW.timestamp() * 1000)

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
FED_CALENDAR = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_RELEASES = "https://www.federalreserve.gov/newsevents/pressreleases/{year}-press-fomc.htm"
BOK_CALENDAR = "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A"
KIND_IR = "https://kind.krx.co.kr/corpgeneral/irschedule.do"
DART_LIST = "https://opendart.fss.or.kr/api/list.json"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ALPHA = "https://www.alphavantage.co/query"
LL2_UPCOMING = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"
LL2_PREVIOUS = "https://ll.thespacedevs.com/2.3.0/launches/previous/"

HEADERS = {
    "User-Agent": "MarketAlarmCollector/1.2 (+https://github.com/Loshin4/market_alarm)",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


US_COMPANY_NAMES = {
    "NVDA": "엔비디아", "MSFT": "마이크로소프트", "AAPL": "애플",
    "AMZN": "아마존", "META": "메타", "GOOGL": "알파벳", "GOOG": "알파벳",
    "TSLA": "테슬라", "AVGO": "브로드컴", "AMD": "AMD", "MU": "마이크론",
    "INTC": "인텔", "SNDK": "샌디스크", "WDC": "웨스턴디지털", "QCOM": "퀄컴",
    "ARM": "Arm", "TSM": "TSMC", "ASML": "ASML", "PLTR": "팔란티어",
    "NOW": "서비스나우", "ORCL": "오라클", "CRM": "세일즈포스", "IBM": "IBM",
    "NFLX": "넷플릭스", "ADBE": "어도비", "CSCO": "시스코", "DELL": "델",
    "HPE": "HPE", "SMCI": "슈퍼마이크로컴퓨터", "MRVL": "마벨테크놀로지",
    "CEG": "컨스텔레이션 에너지", "VST": "비스트라", "ETN": "이튼",
    "NVT": "엔벤트", "GEV": "GE 버노바", "ANET": "아리스타 네트웍스",
    "LRCX": "램리서치", "AMAT": "어플라이드 머티어리얼즈", "KLAC": "KLA",
    "TXN": "텍사스 인스트루먼트", "NXPI": "NXP", "MCHP": "마이크로칩",
    "COIN": "코인베이스", "HOOD": "로빈후드", "JPM": "JP모건", "BAC": "뱅크오브아메리카",
    "GS": "골드만삭스", "MS": "모건스탠리", "WMT": "월마트", "COST": "코스트코",
    "DIS": "디즈니", "UBER": "우버", "ABNB": "에어비앤비", "BA": "보잉",
}

VERY_IMPORTANT_US = {
    "NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "AMD", "MU", "INTC", "TSM", "ASML",
}
IMPORTANT_US = {
    "SNDK", "WDC", "QCOM", "ARM", "PLTR", "NOW", "ORCL", "CRM", "NFLX",
    "SMCI", "MRVL", "CEG", "VST", "ETN", "NVT", "GEV", "ANET", "LRCX",
    "AMAT", "KLAC", "TXN", "COIN", "JPM", "BAC", "GS", "MS", "BA",
}

VERY_IMPORTANT_KR = {"삼성전자", "SK하이닉스"}
IMPORTANT_KR_KEYWORDS = {
    "한미반도체", "LG에너지솔루션", "현대차", "기아", "NAVER", "카카오",
    "삼성바이오로직스", "셀트리온", "두산에너빌리티", "HD현대일렉트릭",
    "LS ELECTRIC", "한화에어로스페이스", "SK이노베이션", "LG전자",
}


SOURCE_LABELS = {
    "bls": "미국 노동통계국(BLS)",
    "bea": "미국 경제분석국(BEA)",
    "fomc": "미국 연방준비제도",
    "bok": "한국은행",
    "kind": "한국거래소(KIND)",
    "dart": "금융감독원 전자공시(OpenDART)",
    "alpha": "미국 기업 실적 데이터",
    "spacex": "우주 발사 일정 데이터",
    "bls_results": "미국 노동통계 발표 결과",
}


@dataclass
class SourceResult:
    key: str
    events: list[dict[str, Any]]
    ok: bool = True
    message: str = ""


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def http_get(url: str, *, params: dict[str, Any] | None = None, timeout: int = 30) -> requests.Response:
    response = SESSION.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(p).strip().lower() for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return int(dt.astimezone(UTC).timestamp() * 1000)


def iso_utc(dt: datetime | None = None) -> str:
    value = (dt or NOW).astimezone(UTC).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def event(
    *,
    event_id: str,
    title: str,
    when: datetime,
    source_key: str,
    source: str,
    source_url: str,
    category: str,
    importance: int,
    status: str = "scheduled",
    summary: str = "",
    symbol: str = "",
    market: str = "",
    actual: str = "",
    expected: str = "",
    previous: str = "",
    rating: int = 0,
    rating_label: str = "",
    official: bool = True,
    all_day: bool = False,
    confidence: str = "official",
) -> dict[str, Any]:
    rating = max(-2, min(2, int(rating)))
    return {
        "id": event_id,
        "title": clean_text(title),
        "time": epoch_ms(when),
        "allDay": bool(all_day),
        "sourceKey": source_key,
        "source": source,
        "sourceUrl": source_url,
        "category": category,
        "importance": max(1, min(5, int(importance))),
        "status": status,
        "summary": clean_text(summary),
        "symbol": symbol,
        "market": market,
        "actual": actual,
        "expected": expected,
        "previous": previous,
        "rating": rating,
        "ratingLabel": rating_label or rating_text(rating),
        "official": bool(official),
        "confidence": confidence,
        "updatedAt": iso_utc(),
    }


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def rating_text(rating: int) -> str:
    return {2: "🟢🟢 매우 좋음", 1: "🟢 좋음", 0: "⚪ 중립", -1: "🔴 나쁨", -2: "🔴🔴 매우 나쁨"}.get(rating, "⚪ 중립")


def parse_ics(raw: str, *, source_key: str, source: str, source_url: str, category: str) -> list[dict[str, Any]]:
    unfolded = re.sub(r"\r?\n[ \t]", "", raw)
    blocks = unfolded.split("BEGIN:VEVENT")[1:]
    out: list[dict[str, Any]] = []
    for block in blocks:
        fields: dict[str, str] = {}
        raw_lines: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            left, value = line.split(":", 1)
            name = left.split(";", 1)[0].upper()
            if name not in fields:
                fields[name] = value.replace("\\,", ",").replace("\\n", " ").replace("\\;", ";")
                raw_lines[name] = left
        summary = clean_text(fields.get("SUMMARY"))
        dt_value = fields.get("DTSTART", "")
        if not summary or not dt_value:
            continue
        left = raw_lines.get("DTSTART", "")
        all_day = "VALUE=DATE" in left.upper() or bool(re.fullmatch(r"\d{8}", dt_value))
        tzid_match = re.search(r"TZID=([^;:]+)", left, re.I)
        tzid = tzid_match.group(1) if tzid_match else ""
        try:
            when = parse_ics_datetime(dt_value, tzid, all_day)
        except Exception:
            continue
        title = translate_macro_title(summary)
        importance = macro_importance(title)
        uid = fields.get("UID") or stable_id(source_key, title, when.date())
        out.append(event(
            event_id=f"{source_key}-{stable_id(uid)}",
            title=title,
            when=when,
            source_key=source_key,
            source=source,
            source_url=fields.get("URL") or source_url,
            category=category,
            importance=importance,
            all_day=all_day,
        ))
    return out


def parse_ics_datetime(value: str, tzid: str, all_day: bool) -> datetime:
    if all_day:
        d = datetime.strptime(value[:8], "%Y%m%d").date()
        return datetime.combine(d, datetime.min.time().replace(hour=12), tzinfo=KST)
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    fmt = "%Y%m%dT%H%M%S" if len(value) >= 15 else "%Y%m%dT%H%M"
    naive = datetime.strptime(value[:15] if len(value) >= 15 else value, fmt)
    zone = ZoneInfo(tzid) if tzid else ET
    return naive.replace(tzinfo=zone)


def translate_macro_title(title: str) -> str:
    """공식 일정 제목을 한국어로 정규화한다.

    CPI·PPI·GDP·PCE·JOLTS처럼 시장에서 통용되는 약어는 유지한다.
    매핑되지 않은 영문 제목은 출처별 일반 한국어 제목으로 바꿔 앱에
    긴 영문 문장이 노출되지 않게 한다.
    """
    replacements = {
        "Consumer Price Index": "미국 소비자물가지수(CPI)",
        "Producer Price Index": "미국 생산자물가지수(PPI)",
        "The Employment Situation": "미국 고용보고서",
        "Employment Situation": "미국 고용보고서",
        "Job Openings and Labor Turnover Survey": "미국 구인·이직 보고서(JOLTS)",
        "Gross Domestic Product": "미국 국내총생산(GDP)",
        "Personal Income and Outlays": "미국 개인소득·소비 및 개인소비지출물가(PCE)",
        "U.S. International Trade in Goods and Services": "미국 무역수지",
        "Retail Sales": "미국 소매판매",
        "Employment Cost Index": "미국 고용비용지수(ECI)",
        "Import and Export Price Indexes": "미국 수출입물가지수",
        "U.S. Import and Export Price Indexes": "미국 수출입물가지수",
        "Real Earnings": "미국 실질임금",
        "Productivity and Costs": "미국 생산성·노동비용",
        "State Employment and Unemployment": "미국 주별 고용·실업",
        "Metropolitan Area Employment and Unemployment": "미국 대도시권 고용·실업",
        "County Employment and Wages": "미국 지역별 고용·임금",
        "Union Members": "미국 노동조합 가입 현황",
        "Consumer Expenditures": "미국 소비지출",
        "Usual Weekly Earnings": "미국 주간 임금",
        "Business Employment Dynamics": "미국 기업 고용 변동",
        "Employee Benefits": "미국 근로자 복리후생",
        "International Transactions and Investment Position": "미국 국제거래·투자 현황",
        "Corporate Profits": "미국 기업이익",
        "GDP by Industry": "미국 산업별 국내총생산(GDP)",
        "GDP by State": "미국 주별 국내총생산(GDP)",
        "Personal Consumption Expenditures by State": "미국 주별 개인소비지출",
    }
    out = clean_text(title)
    for old, new in sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True):
        out = re.sub(re.escape(old), new, out, flags=re.I)
    # Remove common release suffixes that otherwise remain in English.
    out = re.sub(r"\b(news release|release|report|annual|quarterly|monthly)\b", "", out, flags=re.I)
    out = clean_text(out.strip(" -–—:|"))
    if re.search(r"[A-Za-z]{3,}", out):
        # Keep only widely used market abbreviations; hide any residual English sentence.
        allowed = re.sub(r"\b(CPI|PPI|GDP|PCE|JOLTS|ECI|FOMC)\b", "", out, flags=re.I)
        if re.search(r"[A-Za-z]{3,}", allowed):
            return "미국 주요 경제지표 발표"
    return out or "미국 주요 경제지표 발표"


def company_display_name(symbol: str, raw_name: str = "") -> str:
    symbol = clean_text(symbol).upper()
    name = US_COMPANY_NAMES.get(symbol, "")
    if name:
        return f"{name}({symbol})"
    # 전체 기업을 수집하므로 번역 사전에 없는 회사는 영문 회사명 대신 종목코드만 표시한다.
    # 이렇게 하면 앱 화면은 한국어 중심으로 유지되면서도 회사를 정확히 식별할 수 있다.
    return symbol or clean_text(raw_name) or "미국 기업"


def us_importance(symbol: str) -> int:
    symbol = clean_text(symbol).upper()
    if symbol in VERY_IMPORTANT_US:
        return 5
    if symbol in IMPORTANT_US:
        return 4
    return 3


def kr_importance(company: str) -> int:
    compact = re.sub(r"\s+", "", clean_text(company)).upper()
    if any(re.sub(r"\s+", "", x).upper() in compact for x in VERY_IMPORTANT_KR):
        return 5
    if any(re.sub(r"\s+", "", x).upper() in compact for x in IMPORTANT_KR_KEYWORDS):
        return 4
    return 3


def koreanize_earnings_title(value: str, year: int | None = None) -> str:
    text = clean_text(value)
    lower = text.lower()
    y = year or NOW.astimezone(KST).year
    quarter = ""
    if any(k in lower for k in ("first quarter", "1q", "1st quarter")):
        quarter = "1분기"
    elif any(k in lower for k in ("second quarter", "2q", "2nd quarter")):
        quarter = "2분기"
    elif any(k in lower for k in ("third quarter", "3q", "3rd quarter")):
        quarter = "3분기"
    elif any(k in lower for k in ("fourth quarter", "4q", "4th quarter")):
        quarter = "4분기"
    if re.search(r"earnings|financial results|results announcement|results release", lower):
        return f"{y}년 {quarter + ' ' if quarter else ''}실적 발표".strip()
    text = re.sub(r"\bIR\b", "IR", text, flags=re.I)
    return text


def koreanize_space_text(value: Any) -> str:
    text = clean_text(value)
    replacements = {
        "SpaceX": "스페이스X", "Starship": "스타십", "Starlink": "스타링크",
        "Falcon Heavy": "팰컨 헤비", "Falcon 9": "팰컨 9", "Falcon": "팰컨",
        "Crew Dragon": "크루 드래건", "Dragon": "드래건",
        "Kennedy Space Center": "케네디 우주센터",
        "Cape Canaveral Space Force Station": "케이프커내버럴 우주군 기지",
        "Vandenberg Space Force Base": "밴덴버그 우주군 기지",
        "Starbase": "스타베이스", "Launch Complex": "발사단지",
        "Space Launch Complex": "우주발사단지", "Group": "그룹",
        "Flight": "비행", "Mission": "임무", "Test Flight": "시험비행",
        "Success": "성공", "Failure": "실패", "Go for Launch": "발사 확정",
        "To Be Confirmed": "확인 중", "To Be Determined": "미정",
    }
    for old, new in sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True):
        text = re.sub(re.escape(old), new, text, flags=re.I)
    # Mission numbers and proper codes are kept, but long English descriptions are omitted.
    return clean_text(text)


def macro_importance(title: str) -> int:
    x = title.lower()
    if any(k in x for k in ("cpi", "고용보고서", "gross domestic product", "미국 gdp", "pce", "fomc", "기준금리")):
        return 5
    if any(k in x for k in ("ppi", "jolts", "retail", "소매", "eci", "무역수지", "실업")):
        return 4
    return 3


def collect_bls() -> SourceResult:
    raw = http_get(BLS_ICS).text
    return SourceResult("bls", parse_ics(raw, source_key="bls", source=SOURCE_LABELS["bls"], source_url=BLS_ICS, category="macro"))


def collect_bea() -> SourceResult:
    raw = http_get(BEA_ICS).text
    return SourceResult("bea", parse_ics(raw, source_key="bea", source=SOURCE_LABELS["bea"], source_url=BEA_ICS, category="macro"))


def collect_fomc() -> SourceResult:
    html = http_get(FED_CALENDAR).text
    text = clean_text(BeautifulSoup(html, "html.parser").get_text(" "))
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    out: list[dict[str, Any]] = []
    for year in range(NOW.year - 1, NOW.year + 3):
        marker = f"{year} FOMC Meetings"
        start = text.find(marker)
        if start < 0:
            continue
        end_candidates = [text.find(f"{other} FOMC Meetings", start + len(marker)) for other in range(year + 1, year + 3)]
        end_candidates = [x for x in end_candidates if x >= 0]
        section = text[start:(min(end_candidates) if end_candidates else start + 5000)]
        pattern = re.compile(rf"\b({months})\s+(\d{{1,2}})(?:\s*[-–]\s*(\d{{1,2}}))?\*?", re.I)
        for match in pattern.finditer(section):
            month = datetime.strptime(match.group(1)[:3], "%b").month
            day = int(match.group(3) or match.group(2))
            try:
                when = datetime(year, month, day, 14, 0, tzinfo=ET)
            except ValueError:
                continue
            out.append(event(
                event_id=f"fomc-{year}-{month:02d}-{day:02d}",
                title="미국 FOMC 금리결정·성명서",
                when=when,
                source_key="fomc",
                source=SOURCE_LABELS["fomc"],
                source_url=FED_CALENDAR,
                category="central_bank",
                importance=5,
                market="US",
            ))
    # Official statement releases update the scheduled item to released.
    try:
        release_html = http_get(FED_RELEASES.format(year=NOW.year)).text
        soup = BeautifulSoup(release_html, "html.parser")
        for link in soup.find_all("a", href=True):
            label = clean_text(link.get_text(" "))
            if "issues FOMC statement" not in label:
                continue
            container_text = clean_text(link.parent.get_text(" ") if link.parent else "")
            dm = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", container_text)
            if not dm:
                continue
            month, day, year = map(int, dm.groups())
            when = datetime(year, month, day, 14, 0, tzinfo=ET)
            out.append(event(
                event_id=f"fomc-{year}-{month:02d}-{day:02d}",
                title="미국 FOMC 금리결정·성명서",
                when=when,
                source_key="fomc",
                source=SOURCE_LABELS["fomc"],
                source_url=urljoin(FED_CALENDAR, link["href"]),
                category="central_bank",
                importance=5,
                status="released",
                summary="⚪ FOMC 공식 성명서 공개 · 금리 결정과 문구 변화 확인",
                market="US",
                official=True,
            ))
    except Exception:
        pass
    if not out:
        raise RuntimeError("FOMC 일정을 해석하지 못함")
    return SourceResult("fomc", out)


def collect_bok() -> SourceResult:
    html = http_get(BOK_CALENDAR).text
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text(" "))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    date_patterns = [r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})일?", r"(20\d{2})(\d{2})(\d{2})"]
    for pattern in date_patterns:
        for match in re.finditer(pattern, text):
            year, month, day = map(int, match.groups())
            if year < NOW.year - 1 or year > NOW.year + 2:
                continue
            key = f"{year}-{month:02d}-{day:02d}"
            if key in seen:
                continue
            around = text[max(0, match.start() - 100):match.end() + 100]
            if not any(k in around for k in ("금융통화위원회", "통화정책방향", "기준금리")):
                continue
            seen.add(key)
            when = datetime(year, month, day, 10, 0, tzinfo=KST)
            out.append(event(
                event_id=f"bok-{key}",
                title="한국은행 기준금리 결정",
                when=when,
                source_key="bok",
                source=SOURCE_LABELS["bok"],
                source_url=BOK_CALENDAR,
                category="central_bank",
                importance=5,
                market="KR",
                confidence="official_schedule",
            ))
    if not out:
        raise RuntimeError("한국은행 일정을 해석하지 못함")
    return SourceResult("bok", out)


def company_lookup(config: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    name_to_code: dict[str, str] = {}
    code_to_name: dict[str, str] = {}
    for item in config.get("kr", []):
        name = clean_text(item.get("name"))
        code = clean_text(item.get("code"))
        if name:
            name_to_code[re.sub(r"\s+", "", name)] = code
        if code:
            code_to_name[code] = name
    return name_to_code, code_to_name



def earnings_period_key(raw_title: str, event_date: date) -> str:
    """Return a stable earnings period key so a time/date correction updates one event."""
    text = clean_text(raw_title)
    year_match = re.search(r"(20\d{2})", text)
    year = int(year_match.group(1)) if year_match else event_date.year
    quarter_patterns = [
        (r"(?:제?\s*)?1\s*분기|\b1Q\s*\d{0,4}\b|\bQ1\b|first\s+quarter", "Q1"),
        (r"(?:제?\s*)?2\s*분기|\b2Q\s*\d{0,4}\b|\bQ2\b|second\s+quarter", "Q2"),
        (r"(?:제?\s*)?3\s*분기|\b3Q\s*\d{0,4}\b|\bQ3\b|third\s+quarter", "Q3"),
        (r"(?:제?\s*)?4\s*분기|\b4Q\s*\d{0,4}\b|\bQ4\b|fourth\s+quarter", "Q4"),
        (r"상반기|반기|\bH1\b|first\s+half", "H1"),
        (r"하반기|\bH2\b|second\s+half", "H2"),
        (r"연간|연도|사업연도|\bFY\b|full\s+year|annual", "FY"),
    ]
    low = text.lower()
    for pattern, label in quarter_patterns:
        if re.search(pattern, low, re.I):
            return f"{year}-{label}"
    # A stable month bucket is safer than including the exact date/time.
    return f"{year}-M{event_date.month:02d}"


def parse_kind_page(html: str, page: int) -> tuple[list[dict[str, Any]], int | None, int | None, tuple[str, ...]]:
    """Parse one KIND IR page and return earnings events plus pagination metadata."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr") or soup.find_all("tr")
    events: list[dict[str, Any]] = []
    row_keys: list[str] = []
    for row in rows:
        cells = [clean_text(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
        date_index = next((i for i, cell in enumerate(cells)
                           if re.fullmatch(r"20\d{2}[.-]\d{1,2}[.-]\d{1,2}", cell)), -1)
        if date_index < 3:
            continue
        date_text = cells[date_index].replace(".", "-")
        try:
            d = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        company = re.sub(r"^(유가증권|코스닥|코넥스)\s*", "", cells[date_index - 3]).strip()
        raw_title = cells[date_index - 2]
        if not company or not raw_title:
            continue
        time_text = cells[date_index + 1] if date_index + 1 < len(cells) else ""
        row_number = cells[0] if cells and re.fullmatch(r"\d+", cells[0]) else ""
        row_keys.append(row_number or stable_id(company, raw_title, date_text, time_text))
        low = raw_title.lower()
        is_earnings = any(k in low for k in (
            "실적", "경영실적", "잠정", "earnings", "financial results",
            "results announcement", "results release", "quarter earnings",
        ))
        if not is_earnings:
            continue
        title = koreanize_earnings_title(raw_title, d.year)
        tm = re.search(r"(\d{1,2}):(\d{2})", time_text)
        hour, minute = (int(tm.group(1)), int(tm.group(2))) if tm else (12, 0)
        all_day = tm is None
        when = datetime(d.year, d.month, d.day, hour, minute, tzinfo=KST)
        link = row.find("a", href=True)
        source_url = urljoin(KIND_IR, link["href"]) if link else f"{KIND_IR}?gubun=iRSchedule&method=searchIRScheduleMain"
        compact_company = re.sub(r"\s+", "", company)
        period = earnings_period_key(raw_title, d)
        eid = f"kr-earnings-{stable_id(compact_company)}-{period}"
        parsed_item = event(
            event_id=eid,
            title=f"{company} {title}",
            when=when,
            source_key="kind",
            source=SOURCE_LABELS["kind"],
            source_url=source_url,
            category="earnings",
            importance=kr_importance(company),
            market="KR",
            all_day=all_day,
            confidence="official_schedule",
        )
        parsed_item["_rawTitleHasKorean"] = bool(re.search(r"[가-힣]", raw_title))
        events.append(parsed_item)
    text = clean_text(soup.get_text(" "))
    page_match = re.search(r"전체\s*[\d,]+건\s*:\s*(\d+)\s*/\s*(\d+)", text)
    current_page = int(page_match.group(1)) if page_match else None
    total_pages = int(page_match.group(2)) if page_match else None
    return events, current_page, total_pages, tuple(row_keys)


def fetch_kind_page(page: int) -> str:
    """KIND pagination is form-based; POST is required for pageIndex to take effect."""
    payload = {
        "gubun": "iRSchedule",
        "method": "searchIRScheduleMain",
        "pageIndex": str(page),
    }
    response = SESSION.post(KIND_IR, data=payload, timeout=30)
    response.raise_for_status()
    return response.text


def collect_kind(config: dict[str, Any] | None = None) -> SourceResult:
    """Collect all earnings-related IR schedules from every KIND result page.

    The old implementation sent pageIndex with GET, but KIND pagination is form-based,
    so page 1 was repeatedly downloaded. This implementation uses POST, validates the
    page marker, and rejects incomplete/repeated snapshots instead of deleting good data.
    """
    out_by_id: dict[str, dict[str, Any]] = {}
    seen_signatures: set[tuple[str, ...]] = set()
    expected_total_pages: int | None = None
    raw_rows = 0
    page = 1
    while True:
        html = fetch_kind_page(page)
        parsed, current_page, total_pages, signature = parse_kind_page(html, page)
        if expected_total_pages is None and total_pages:
            expected_total_pages = total_pages
        if page > 1 and current_page is not None and current_page != page:
            raise RuntimeError(f"KIND 페이지 이동 실패: 요청 {page}, 응답 {current_page}")
        if page > 1 and signature and signature in seen_signatures:
            raise RuntimeError(f"KIND {page}페이지가 이전 페이지와 중복됨")
        if signature:
            seen_signatures.add(signature)
            raw_rows += len(signature)
        for item in parsed:
            eid = str(item.get("id"))
            old = out_by_id.get(eid)
            old_korean = bool(old and old.get("_rawTitleHasKorean"))
            new_korean = bool(item.get("_rawTitleHasKorean"))
            # Prefer Korean duplicates; otherwise prefer the latest schedule time.
            if (
                old is None
                or (new_korean and not old_korean)
                or (new_korean == old_korean and int(item.get("time", 0)) >= int(old.get("time", 0)))
            ):
                out_by_id[eid] = item
        last_page = expected_total_pages or total_pages or 1
        if page >= last_page:
            break
        page += 1
        if page > 100:
            raise RuntimeError("KIND 페이지 수가 비정상적으로 많음")
    out = list(out_by_id.values())
    for item in out:
        item.pop("_rawTitleHasKorean", None)
    if not out:
        raise RuntimeError("KIND 전체 실적 일정이 비어 있음")
    if expected_total_pages and len(seen_signatures) < expected_total_pages:
        raise RuntimeError(f"KIND 수집 불완전: {len(seen_signatures)}/{expected_total_pages}페이지")
    return SourceResult("kind", out, True, f"IR 원본 {raw_rows}건 중 실적 일정 {len(out)}개")

def collect_dart(config: dict[str, Any] | None, api_key: str) -> SourceResult:
    if not api_key:
        return SourceResult("dart", [], False, "OpenDART 인증키 미설정")
    begin = (NOW.astimezone(KST).date() - timedelta(days=14)).strftime("%Y%m%d")
    end = NOW.astimezone(KST).date().strftime("%Y%m%d")
    out: list[dict[str, Any]] = []
    page = 1
    while page <= 5:
        params = {
            "crtfc_key": api_key,
            "bgn_de": begin,
            "end_de": end,
            "last_reprt_at": "Y",
            "page_no": page,
            "page_count": 100,
            "sort": "date",
            "sort_mth": "desc",
        }
        payload = http_get(DART_LIST, params=params).json()
        status = payload.get("status")
        if status not in ("000", None):
            raise RuntimeError(payload.get("message", f"DART status {status}"))
        rows = payload.get("list") or []
        for row in rows:
            report = clean_text(row.get("report_nm"))
            corp_name = clean_text(row.get("corp_name"))
            stock_code = clean_text(row.get("stock_code"))
            low = report.lower()
            is_result = any(k in low for k in ("잠정실적", "영업(잠정)실적", "매출액또는손익구조", "분기보고서", "반기보고서", "사업보고서"))
            if not is_result:
                continue
            receipt = clean_text(row.get("rcept_no"))
            receipt_date = clean_text(row.get("rcept_dt"))
            try:
                d = datetime.strptime(receipt_date, "%Y%m%d").date()
            except ValueError:
                continue
            when = datetime(d.year, d.month, d.day, 18, 0, tzinfo=KST)
            source_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"
            period = infer_report_period(report, d)
            eid = f"kr-result-{stock_code or stable_id(corp_name)}-{period}"
            summary = f"⚪ {report} 공식 공시 확인"
            out.append(event(
                event_id=eid,
                title=f"{corp_name} 실적 결과",
                when=when,
                source_key="dart",
                source=SOURCE_LABELS["dart"],
                source_url=source_url,
                category="earnings",
                importance=kr_importance(corp_name),
                status="released",
                summary=summary,
                symbol=stock_code,
                market="KR",
                official=True,
            ))
        total_page = int(payload.get("total_page") or 1)
        if page >= total_page:
            break
        page += 1
    return SourceResult("dart", out)


def infer_report_period(report: str, d: date) -> str:
    if "사업보고서" in report:
        return f"{d.year - 1}-FY"
    if "반기보고서" in report:
        return f"{d.year}-H1"
    if "분기보고서" in report:
        return f"{d.year}-Q{1 if d.month <= 5 else 3}"
    return d.isoformat()


def collect_alpha(config: dict[str, Any] | None, api_key: str, state: dict[str, Any], force: bool) -> SourceResult:
    """미국 전체 실적 달력과 제한된 결과 확인을 수집한다.

    EARNINGS_CALENDAR는 symbol을 지정하지 않아 전체 목록을 받는다. 무료 호출량을
    지키기 위해 달력은 하루 한 번, 결과는 하루 최대 20개 기업만 중요도·발표시각
    순으로 확인한다. 일정 자체는 모든 기업이 앱에 반영된다.
    """
    if not api_key:
        return SourceResult("alpha", [], False, "미국 실적 데이터 인증키 미설정")
    previous_events = load_json(EVENTS_FILE, {}).get("events", [])
    out: list[dict[str, Any]] = []
    last = parse_iso(state.get("alphaCalendarCheckedAt"))
    should_calendar = force or not last or NOW - last >= timedelta(hours=22)

    if should_calendar:
        response = http_get(ALPHA, params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": api_key})
        text = response.text
        if text.lstrip().startswith("{"):
            payload = response.json()
            raise RuntimeError(payload.get("Information") or payload.get("Note") or "미국 전체 실적 달력 조회 오류")
        rows = list(csv.DictReader(io.StringIO(text)))
        for raw in rows:
            row = {k: clean_text(v) for k, v in raw.items()}
            symbol = row.get("symbol", "").upper()
            report_date = row.get("reportDate", "") or row.get("report_date", "")
            if not symbol or not report_date:
                continue
            country = (row.get("country") or "").lower()
            currency = (row.get("currency") or "").upper()
            # 미국 상장 실적 달력 중심. 국가가 비어 있는 행은 유지한다.
            if country and not any(k in country for k in ("united states", "usa", "u.s.")) and currency not in ("USD", ""):
                continue
            try:
                d = datetime.strptime(report_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            report_time = (row.get("reportTime") or row.get("report_time") or "").lower()
            if any(k in report_time for k in ("after", "post")):
                hour, all_day, timing = 16, False, "미국 장 마감 후"
            elif any(k in report_time for k in ("before", "pre")):
                hour, all_day, timing = 8, False, "미국 장 시작 전"
            else:
                hour, all_day, timing = 12, True, "발표 시간 미정"
            when = datetime(d.year, d.month, d.day, hour, 0, tzinfo=ET)
            estimate = row.get("estimate", "") or row.get("estimatedEPS", "")
            fiscal = row.get("fiscalDateEnding", "")
            raw_name = row.get("name", "")
            summary_parts = [timing]
            if estimate:
                summary_parts.append(f"예상 EPS {estimate}")
            if fiscal:
                summary_parts.append(f"회계기간 {fiscal}")
            out.append(event(
                event_id=f"us-earnings-{symbol}-{d.isoformat()}",
                title=f"{company_display_name(symbol, raw_name)} 실적 발표",
                when=when,
                source_key="alpha",
                source=SOURCE_LABELS["alpha"],
                source_url=f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&symbol={symbol}",
                category="earnings",
                importance=us_importance(symbol),
                summary=" · ".join(summary_parts),
                symbol=symbol,
                market="US",
                expected=estimate,
                all_day=all_day,
                confidence="provider",
            ))
        state["alphaCalendarCheckedAt"] = iso_utc()
    else:
        # 호출 제한으로 달력을 다시 받지 않는 시간에는 이전 전체 미국 일정을 유지한다.
        out.extend(item for item in previous_events
                   if item.get("sourceKey") == "alpha" and item.get("status") == "scheduled")

    # 무료 호출량: 날짜가 바뀌면 일일 결과 확인 횟수를 초기화한다.
    today_key = NOW.astimezone(ET).date().isoformat()
    quota = state.setdefault("alphaDailyQuota", {})
    if quota.get("date") != today_key:
        quota.clear()
        quota.update({"date": today_key, "resultCalls": 0})
    used = int(quota.get("resultCalls", 0))
    remaining = max(0, 20 - used)

    cutoff_start = NOW.astimezone(ET).date() - timedelta(days=3)
    cutoff_end = NOW.astimezone(ET).date() + timedelta(days=1)
    candidates: dict[str, dict[str, Any]] = {}
    for item in out + previous_events:
        if item.get("sourceKey") != "alpha" or item.get("status") != "scheduled":
            continue
        symbol = clean_text(item.get("symbol")).upper()
        if not symbol:
            continue
        d = datetime.fromtimestamp(int(item.get("time", 0)) / 1000, UTC).astimezone(ET).date()
        if cutoff_start <= d <= cutoff_end:
            current = candidates.get(symbol)
            if current is None or (int(item.get("importance", 0)), -int(item.get("time", 0))) > (int(current.get("importance", 0)), -int(current.get("time", 0))):
                candidates[symbol] = item

    checked = state.setdefault("alphaResultChecked", {})
    ordered = sorted(candidates.values(), key=lambda x: (-int(x.get("importance", 0)), int(x.get("time", 0)), str(x.get("symbol", ""))))
    for scheduled in ordered:
        if remaining <= 0:
            break
        symbol = clean_text(scheduled.get("symbol")).upper()
        checked_at = parse_iso(checked.get(symbol))
        if not force and checked_at and NOW - checked_at < timedelta(hours=8):
            continue
        payload = http_get(ALPHA, params={"function": "EARNINGS", "symbol": symbol, "apikey": api_key}).json()
        checked[symbol] = iso_utc()
        quota["resultCalls"] = int(quota.get("resultCalls", 0)) + 1
        remaining -= 1
        if payload.get("Information") or payload.get("Note"):
            break
        quarters = payload.get("quarterlyEarnings") or []
        if not quarters:
            continue
        latest = quarters[0]
        try:
            d = datetime.strptime(latest.get("reportedDate", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff_start - timedelta(days=5):
            continue
        actual = safe_float(latest.get("reportedEPS"))
        estimate = safe_float(latest.get("estimatedEPS"))
        surprise = safe_float(latest.get("surprisePercentage"))
        if surprise is None and estimate not in (None, 0) and actual is not None:
            surprise = (actual - estimate) / abs(estimate) * 100
        rating = 2 if surprise is not None and surprise >= 5 else 1 if surprise is not None and surprise > 0 else -2 if surprise is not None and surprise <= -5 else -1 if surprise is not None and surprise < 0 else 0
        summary = f"{rating_text(rating)} · EPS {fmt_num(actual)} / 예상 {fmt_num(estimate)}"
        if surprise is not None:
            summary += f" · {surprise:+.1f}%"
        when = datetime(d.year, d.month, d.day, 16, 5, tzinfo=ET)
        out.append(event(
            event_id=f"us-earnings-{symbol}-{d.isoformat()}",
            title=f"{company_display_name(symbol)} 실적 결과",
            when=when,
            source_key="alpha",
            source=SOURCE_LABELS["alpha"],
            source_url=f"https://www.alphavantage.co/query?function=EARNINGS&symbol={symbol}",
            category="earnings",
            importance=us_importance(symbol),
            status="released",
            summary=summary,
            symbol=symbol,
            market="US",
            actual=fmt_num(actual),
            expected=fmt_num(estimate),
            rating=rating,
            official=False,
            confidence="provider",
        ))
    return SourceResult("alpha", out, True, f"전체 실적 일정 {sum(1 for x in out if x.get('status') == 'scheduled')}개 · 오늘 결과 확인 {quota.get('resultCalls', 0)}/20")

def collect_spacex() -> SourceResult:
    params_upcoming = {"limit": 60, "ordering": "net", "lsp__name": "SpaceX"}
    params_previous = {"limit": 30, "ordering": "-net", "lsp__name": "SpaceX"}
    payloads = [http_get(LL2_UPCOMING, params=params_upcoming).json(), http_get(LL2_PREVIOUS, params=params_previous).json()]
    out: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads):
        previous = index == 1
        for row in payload.get("results") or []:
            raw_provider = clean_text((row.get("launch_service_provider") or {}).get("name"))
            raw_name = clean_text(row.get("name") or "SpaceX launch")
            combined = f"{raw_provider} {raw_name}".lower()
            if not any(k in combined for k in ("spacex", "starship", "falcon", "dragon")):
                continue
            provider = koreanize_space_text(raw_provider)
            name = koreanize_space_text(raw_name)
            dt_value = row.get("net") or row.get("window_start")
            try:
                when = dtparser.isoparse(dt_value)
            except Exception:
                continue
            delta = when.astimezone(UTC) - NOW
            if previous and delta < timedelta(days=-30):
                continue
            if not previous and delta > timedelta(days=180):
                continue
            status_obj = row.get("status") or {}
            raw_status_name = clean_text(status_obj.get("name"))
            status_name = koreanize_space_text(raw_status_name)
            low_status = raw_status_name.lower()
            released = previous or when.astimezone(UTC) <= NOW
            success = "success" in low_status
            failure = "fail" in low_status
            rocket = koreanize_space_text((((row.get("rocket") or {}).get("configuration") or {}).get("full_name")))
            mission = row.get("mission") or {}
            description = ""  # 긴 영문 임무 설명은 앱에 노출하지 않음
            pad = koreanize_space_text(((row.get("pad") or {}).get("name")))
            title = name if name.startswith("스페이스X") else f"스페이스X {name}"
            importance = 5 if any(k in combined for k in ("starship", "falcon heavy", "crew", "dragon")) else 4
            rating = 1 if success else -2 if failure else 0
            summary_parts = []
            if released:
                summary_parts.append(rating_text(rating) if success or failure else f"⚪ {status_name or '결과 확인'}")
            if rocket:
                summary_parts.append(rocket)
            if pad:
                summary_parts.append(pad)
            if description:
                summary_parts.append(description[:130])
            webcast = row.get("webcast_live")
            source_url = clean_text(row.get("vidURLs") or row.get("url"))
            if not source_url:
                source_url = "https://www.spacex.com/launches/"
            out.append(event(
                event_id=f"space-{row.get('id') or stable_id(name, dt_value)}",
                title=title + (" 결과" if released else ""),
                when=when,
                source_key="spacex",
                source=SOURCE_LABELS["spacex"],
                source_url=source_url,
                category="industry",
                importance=importance,
                status="released" if released else "scheduled",
                summary=" · ".join(summary_parts),
                symbol="SPACEX",
                market="US",
                rating=rating,
                official=False,
                confidence="aggregator",
            ))
    if not out:
        raise RuntimeError("스페이스X 일정이 비어 있음")
    return SourceResult("spacex", out)


def collect_bls_results(events: list[dict[str, Any]]) -> SourceResult:
    series_ids = ["CUUR0000SA0", "WPUFD4", "LNS14000000", "CES0000000001"]
    body = {"seriesid": series_ids, "startyear": str(NOW.year - 2), "endyear": str(NOW.year)}
    response = SESSION.post(BLS_API, json=body, timeout=30)
    response.raise_for_status()
    payload = response.json()
    series = ((payload.get("Results") or {}).get("series") or [])
    values: dict[str, tuple[str, str, int]] = {}
    for item in series:
        sid = item.get("seriesID")
        monthly = [x for x in item.get("data") or [] if str(x.get("period", "")).startswith("M") and x.get("period") != "M13"]
        monthly.sort(key=lambda x: (int(x.get("year", 0)), int(str(x.get("period", "M00"))[1:])), reverse=True)
        nums = [safe_float(x.get("value")) for x in monthly]
        if sid in ("CUUR0000SA0", "WPUFD4") and len(nums) >= 14 and nums[0] and nums[12] and nums[1] and nums[13]:
            actual = (nums[0] / nums[12] - 1) * 100
            previous = (nums[1] / nums[13] - 1) * 100
            rating = 1 if actual < previous else -1 if actual > previous else 0
            key = "CPI" if sid == "CUUR0000SA0" else "PPI"
            values[key] = (f"{actual:.1f}%", f"{previous:.1f}%", rating)
        elif sid == "LNS14000000" and len(nums) >= 2 and nums[0] is not None and nums[1] is not None:
            rating = 1 if nums[0] < nums[1] else -1 if nums[0] > nums[1] else 0
            values["고용보고서"] = (f"실업률 {nums[0]:.1f}%", f"실업률 {nums[1]:.1f}%", rating)
        elif sid == "CES0000000001" and len(nums) >= 3 and None not in nums[:3]:
            actual = nums[0] - nums[1]
            previous = nums[1] - nums[2]
            rating = 1 if actual > previous else -1 if actual < previous else 0
            values["비농업고용"] = (f"{actual:+.0f}K", f"{previous:+.0f}K", rating)
    updated: list[dict[str, Any]] = []
    now_ms = NOW_MS
    for item in events:
        if item.get("sourceKey") != "bls" or int(item.get("time", 0)) > now_ms:
            continue
        title = str(item.get("title", ""))
        key = "CPI" if "CPI" in title or "소비자물가" in title else "PPI" if "PPI" in title or "생산자물가" in title else "고용보고서" if "고용보고서" in title else ""
        if not key:
            continue
        actual, previous, rating = values.get(key, ("", "", 0))
        if key == "고용보고서" and "비농업고용" in values:
            payroll_actual, payroll_previous, payroll_rating = values["비농업고용"]
            summary = f"{rating_text(payroll_rating)} · 비농업고용 {payroll_actual} / 이전 {payroll_previous} · {actual} / 이전 {previous}"
            actual_value = f"고용 {payroll_actual}, {actual}"
            previous_value = f"고용 {payroll_previous}, {previous}"
            rating = payroll_rating if payroll_rating == rating else 0
        else:
            summary = f"{rating_text(rating)} · 실제 {actual} / 이전 {previous} · 예상치 없음"
            actual_value = actual
            previous_value = previous
        clone = dict(item)
        clone.update({
            "status": "released",
            "summary": summary,
            "actual": actual_value,
            "previous": previous_value,
            "expected": "",
            "rating": rating,
            "ratingLabel": rating_text(rating),
            "updatedAt": iso_utc(),
        })
        updated.append(clone)
    return SourceResult("bls_results", updated)


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return dtparser.isoparse(str(value)).astimezone(UTC)
    except Exception:
        return None


def safe_float(value: Any) -> float | None:
    try:
        text = str(value).strip().replace(",", "")
        if text in ("", "None", "null", "None"):
            return None
        return float(text)
    except Exception:
        return None


def fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def merge_events(
    new_events: Iterable[dict[str, Any]],
    old_events: list[dict[str, Any]],
    failed_sources: set[str],
    successful_sources: set[str],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in new_events:
        eid = str(item.get("id", ""))
        if not eid:
            continue
        current = merged.get(eid)
        if current is None or event_score(item) >= event_score(current):
            merged[eid] = item

    # Do not erase a future schedule because it was absent in one partial scrape.
    # Remove it only after three consecutive successful source snapshots miss it.
    missing_counts = state.setdefault("missingScheduledCounts", {})
    seen_ids = set(merged)
    for eid in list(missing_counts):
        if eid in seen_ids:
            missing_counts.pop(eid, None)

    past_cutoff = NOW_MS - int(timedelta(days=120).total_seconds() * 1000)
    future_cutoff = NOW_MS + int(timedelta(days=400).total_seconds() * 1000)
    for old in old_events:
        eid = str(old.get("id", ""))
        when = int(old.get("time", 0))
        source_key = str(old.get("sourceKey", ""))
        keep_history = old.get("status") == "released" and past_cutoff <= when <= future_cutoff
        keep_failed_source = source_key in failed_sources and past_cutoff <= when <= future_cutoff
        keep_missing_grace = False
        if (
            eid
            and eid not in merged
            and old.get("status") == "scheduled"
            and when >= NOW_MS - int(timedelta(days=2).total_seconds() * 1000)
            and source_key in successful_sources
        ):
            count = int(missing_counts.get(eid, 0)) + 1
            missing_counts[eid] = count
            keep_missing_grace = count < 3
        if eid and eid not in merged and (keep_history or keep_failed_source or keep_missing_grace):
            merged[eid] = old

    values = [x for x in merged.values() if past_cutoff <= int(x.get("time", 0)) <= future_cutoff]
    values.sort(key=lambda x: (int(x.get("time", 0)), -int(x.get("importance", 0)), str(x.get("title", ""))))
    return values

def event_score(item: dict[str, Any]) -> tuple[int, int, int]:
    return (
        1 if item.get("status") == "released" else 0,
        1 if item.get("actual") or item.get("summary") else 0,
        int(item.get("importance", 0)),
    )


def detect_changes(old_events: list[dict[str, Any]], new_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_map = {str(x.get("id")): x for x in old_events if x.get("id")}
    changes: list[dict[str, Any]] = []
    for item in new_events:
        old = old_map.get(str(item.get("id")))
        if old is None:
            if int(item.get("time", 0)) >= NOW_MS - int(timedelta(days=2).total_seconds() * 1000):
                changes.append({"type": "new", "event": item, "detectedAt": iso_utc()})
            continue
        if old.get("status") != item.get("status") and item.get("status") == "released":
            changes.append({"type": "released", "event": item, "detectedAt": iso_utc()})
        old_time, new_time = int(old.get("time", 0)), int(item.get("time", 0))
        if abs(old_time - new_time) >= 5 * 60 * 1000:
            changes.append({"type": "time_changed", "event": item, "oldTime": old_time, "detectedAt": iso_utc()})
        if old.get("summary") != item.get("summary") and item.get("status") == "released":
            changes.append({"type": "result_updated", "event": item, "detectedAt": iso_utc()})
    return changes[-200:]


def main() -> int:
    force = os.getenv("FORCE_REFRESH", "").lower() in {"1", "true", "yes"}
    config = load_json(CONFIG_FILE, {})
    old_root = load_json(EVENTS_FILE, {"events": []})
    old_events = old_root.get("events", []) if isinstance(old_root, dict) else []
    state = load_json(STATE_FILE, {})
    dart_key = os.getenv("DART_API_KEY", "").strip()
    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()

    source_functions = [
        ("bls", collect_bls),
        ("bea", collect_bea),
        ("fomc", collect_fomc),
        ("bok", collect_bok),
        ("kind", lambda: collect_kind(config)),
        ("dart", lambda: collect_dart(config, dart_key)),
        ("alpha", lambda: collect_alpha(config, alpha_key, state, force)),
        ("spacex", collect_spacex),
    ]
    results: list[SourceResult] = []
    all_events: list[dict[str, Any]] = []
    failed_sources: set[str] = set()
    for key, fn in source_functions:
        try:
            result = fn()
            results.append(result)
            all_events.extend(result.events)
            if not result.ok:
                failed_sources.add(key)
            print(f"[{key}] {len(result.events)} events" + (f" ({result.message})" if result.message else ""))
        except Exception as exc:
            failed_sources.add(key)
            results.append(SourceResult(key, [], False, str(exc)))
            print(f"[{key}] ERROR: {exc}", file=sys.stderr)

    # BLS official actual/previous values replace matching released schedules.
    try:
        bls_result = collect_bls_results(all_events)
        results.append(bls_result)
        all_events.extend(bls_result.events)
        print(f"[bls_results] {len(bls_result.events)} updates")
    except Exception as exc:
        failed_sources.add("bls_results")
        results.append(SourceResult("bls_results", [], False, str(exc)))
        print(f"[bls_results] ERROR: {exc}", file=sys.stderr)

    successful_sources = {result.key for result in results if result.ok}
    merged = merge_events(all_events, old_events, failed_sources, successful_sources, state)
    changes = detect_changes(old_events, merged)
    counts: dict[str, int] = {}
    for item in merged:
        key = str(item.get("category", "other"))
        counts[key] = counts.get(key, 0) + 1
    sources = {
        result.key: {
            "name": SOURCE_LABELS.get(result.key, result.key),
            "ok": result.ok,
            "count": len(result.events),
            "message": result.message,
        }
        for result in results
    }
    ok_count = sum(1 for result in results if result.ok)
    status = {
        "updatedAt": iso_utc(),
        "ok": ok_count >= 4 and bool(merged),
        "message": f"{len(merged)}개 일정 · 정상 소스 {ok_count}/{len(results)}",
        "counts": counts,
        "sources": sources,
        "failedSources": [SOURCE_LABELS.get(key, key) for key in sorted(failed_sources)],
    }
    save_json(EVENTS_FILE, {"schemaVersion": 2, "updatedAt": iso_utc(), "events": merged})
    previous_changes = load_json(CHANGES_FILE, {"changes": []}).get("changes", [])
    combined_changes = (previous_changes + changes)[-300:]
    save_json(CHANGES_FILE, {"updatedAt": iso_utc(), "changes": combined_changes})
    save_json(STATUS_FILE, status)
    save_json(STATE_FILE, state)
    print(status["message"])
    return 0 if merged else 1


if __name__ == "__main__":
    raise SystemExit(main())
