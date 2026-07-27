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
import zipfile
import html as html_lib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urljoin, unquote, quote
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
DART_IR_PARSER_VERSION = 160
KIND_DETAIL_PARSER_VERSION = 150
DART_RESULT_PARSER_VERSION = 140
US_RESULT_PARSER_VERSION = 140

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
FED_CALENDAR = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_RELEASES = "https://www.federalreserve.gov/newsevents/pressreleases/{year}-press-fomc.htm"
BOK_CALENDAR = "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A"
KIND_IR = "https://kind.krx.co.kr/corpgeneral/irschedule.do?gubun=iRSchedule&method=searchIRScheduleMain"
KIND_IR_CALENDAR = "https://kind.krx.co.kr/corpgeneral/irschedule.do?gubun=iRScheduleCalendar&method=searchIRScheduleMain"
DART_LIST = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT = "https://opendart.fss.or.kr/api/document.xml"
DART_PUBLIC_VIEW = "https://dart.fss.or.kr/dsaf001/main.do"
DART_FINANCIAL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
NASDAQ_EARNINGS = "https://api.nasdaq.com/api/calendar/earnings"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ALPHA = "https://www.alphavantage.co/query"
LL2_UPCOMING = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"
LL2_PREVIOUS = "https://ll.thespacedevs.com/2.3.0/launches/previous/"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
KRX_MARKET_CAP = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 MarketAlarm/1.6",
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
    "LLY": "일라이릴리", "V": "비자", "MA": "마스터카드", "XOM": "엑슨모빌",
    "CVX": "셰브론", "UNH": "유나이티드헬스", "HD": "홈디포", "PG": "프록터앤드갬블",
    "JNJ": "존슨앤드존슨", "ABBV": "애브비", "MRK": "머크", "PEP": "펩시코",
    "KO": "코카콜라", "MCD": "맥도날드", "CAT": "캐터필러", "GE": "GE에어로스페이스",
}

ALWAYS_GENERAL_US = {"ARLP", "AZN"}

VERY_IMPORTANT_US = {
    "NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL", "GOOG", "TSLA",
    "AVGO", "AMD", "MU", "INTC", "TSM", "ASML",
}
IMPORTANT_US = {
    "SNDK", "WDC", "QCOM", "ARM", "PLTR", "NOW", "ORCL", "CRM", "NFLX",
    "SMCI", "MRVL", "CEG", "VST", "ETN", "NVT", "GEV", "ANET", "LRCX",
    "AMAT", "KLAC", "TXN", "COIN", "JPM", "BAC", "GS", "MS", "BA",
    "LLY", "V", "MA", "WMT", "COST", "XOM", "CVX", "UNH", "HD", "PG",
    "JNJ", "ABBV", "MRK", "PEP", "KO", "MCD", "CAT", "GE", "IBM", "CSCO",
    "ADBE", "DELL", "HPE", "UBER", "DIS",
}

KR_MARKET_CAPS: dict[str, int] = {}

VERY_IMPORTANT_KR = {"삼성전자", "SK하이닉스"}
IMPORTANT_KR_KEYWORDS = {
    "한미반도체", "LG에너지솔루션", "현대차", "기아", "NAVER", "카카오",
    "삼성바이오로직스", "셀트리온", "두산에너빌리티", "HD현대일렉트릭",
    "LS ELECTRIC", "한화에어로스페이스", "SK이노베이션", "LG전자", "삼성전기",
    "삼성SDI", "포스코홀딩스", "POSCO홀딩스", "KB금융", "신한지주", "하나금융지주",
    "현대모비스", "삼성물산", "SK텔레콤", "KT", "한국전력", "한화오션",
}


SOURCE_LABELS = {
    "bls": "미국 노동통계국(BLS)",
    "bea": "미국 경제분석국(BEA)",
    "fomc": "미국 연방준비제도",
    "bok": "한국은행",
    "kind": "한국거래소(KIND)",
    "official_ir": "기업 공식 IR 일정",
    "dart_schedule": "OpenDART·KIND 전체 실적 일정 공시",
    "dart": "금융감독원 전자공시(OpenDART)",
    "nasdaq": "나스닥 전체 실적 달력",
    "alpha": "미국 기업 실적 데이터",
    "spacex": "우주 발사 일정 데이터",
    "bls_results": "미국 노동통계 발표 결과",
    "us_results": "미국 기업 실적 결과(SEC·Alpha Vantage)",
    "krx_marketcap": "한국거래소 시가총액",
    "market_indicators": "시장 핵심 지표",
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


def http_post(url: str, *, data: dict[str, Any] | None = None, timeout: int = 30) -> requests.Response:
    response = SESSION.post(url, data=data, timeout=timeout, headers={"Referer": KIND_IR})
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


def parse_market_cap(value: Any) -> float | None:
    text = clean_text(value).replace(",", "").replace("$", "").upper()
    if not text or text in {"N/A", "--", "NONE", "NULL"}:
        return None
    multiplier = 1.0
    if text.endswith("T"):
        multiplier, text = 1_000_000_000_000.0, text[:-1]
    elif text.endswith("B"):
        multiplier, text = 1_000_000_000.0, text[:-1]
    elif text.endswith("M"):
        multiplier, text = 1_000_000.0, text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        digits = re.sub(r"[^0-9.]", "", text)
        try:
            return float(digits) * multiplier if digits else None
        except ValueError:
            return None


def us_importance(symbol: str, market_cap_usd: float | None = None) -> int:
    symbol = clean_text(symbol).upper()
    if symbol in ALWAYS_GENERAL_US:
        return 3
    if symbol in VERY_IMPORTANT_US:
        return 5
    if market_cap_usd is not None and market_cap_usd >= 500_000_000_000:
        return 5
    if symbol in IMPORTANT_US:
        return 4
    # 시가총액만 큰 해외 ADR·중형주는 홈을 어지럽히지 않도록 매우 큰 회사만 자동 승격한다.
    if market_cap_usd is not None and market_cap_usd >= 300_000_000_000:
        return 4
    return 3


def kr_importance(company: str) -> int:
    compact = re.sub(r"\s+", "", clean_text(company)).upper()
    if any(re.sub(r"\s+", "", x).upper() in compact for x in VERY_IMPORTANT_KR):
        return 5
    cap = KR_MARKET_CAPS.get(compact)
    if cap is not None and cap >= 50_000_000_000_000:
        return 5
    if any(re.sub(r"\s+", "", x).upper() in compact for x in IMPORTANT_KR_KEYWORDS):
        return 4
    if cap is not None and cap >= 5_000_000_000_000:
        return 4
    return 3


def refresh_kr_market_caps(state: dict[str, Any], force: bool = False) -> SourceResult:
    global KR_MARKET_CAPS
    checked = parse_iso(state.get("krMarketCapsCheckedAt"))
    cached = state.get("krMarketCaps")
    if isinstance(cached, dict):
        KR_MARKET_CAPS = {str(k): int(v) for k, v in cached.items() if str(v).isdigit()}
    if not force and KR_MARKET_CAPS and checked and NOW - checked < timedelta(hours=20):
        return SourceResult("krx_marketcap", [], True, f"이전 시가총액 {len(KR_MARKET_CAPS)}개 사용")
    last_error = ""
    today = NOW.astimezone(KST).date()
    for offset in range(0, 10):
        d = today - timedelta(days=offset)
        try:
            response = http_post(KRX_MARKET_CAP, data={
                "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
                "locale": "ko_KR", "mktId": "ALL", "trdDd": d.strftime("%Y%m%d"),
                "share": "1", "money": "1", "csvxls_isNo": "false",
            }, timeout=30)
            rows = response.json().get("OutBlock_1") or []
            caps: dict[str, int] = {}
            for row in rows:
                name = re.sub(r"\s+", "", clean_text(row.get("ISU_ABBRV"))).upper()
                raw = re.sub(r"[^0-9]", "", str(row.get("MKTCAP", "")))
                if name and raw:
                    cap = int(raw)
                    if cap >= 1_000_000_000_000:
                        caps[name] = cap
            if caps:
                KR_MARKET_CAPS = caps
                state["krMarketCaps"] = caps
                state["krMarketCapsCheckedAt"] = iso_utc()
                return SourceResult("krx_marketcap", [], True, f"{d.isoformat()} 시가총액 {len(caps)}개")
        except Exception as exc:
            last_error = str(exc)
    if KR_MARKET_CAPS:
        return SourceResult("krx_marketcap", [], False, f"갱신 실패, 이전 시가총액 사용 · {last_error[:90]}")
    return SourceResult("krx_marketcap", [], False, f"시가총액 조회 실패, 기본 중요기업 기준 사용 · {last_error[:90]}")


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


def kind_detail_sequences(html: str) -> set[str]:
    """Extract all KIND IR detail identifiers directly from one HTML response."""
    values: set[str] = set()
    for pattern in (
        r"irSeq(?:=|%3D)(\d+)",
        r"searchIRSchedule(?:Detail|Popup)\s*\(\s*['\"]?(\d+)",
        r"(?:irSeq|seq)\s*[,=:]\s*['\"]?(\d+)",
    ):
        values.update(re.findall(pattern, html, re.I))
    return values


def kind_detail_seq(row: Any) -> str:
    """Extract KIND irSeq from href, onclick or data attributes."""
    blobs: list[str] = []
    for node in row.find_all(True):
        for key, value in node.attrs.items():
            if isinstance(value, list):
                value = " ".join(str(x) for x in value)
            blobs.append(f"{key}={value}")
    joined = " ".join(blobs)
    patterns = (
        r"irSeq\s*=\s*(\d+)",
        r"searchIRSchedule(?:Detail|Popup)\s*\(\s*['\"]?(\d+)",
        r"(?:irSeq|seq)\s*[,=:]\s*['\"]?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, joined, re.I)
        if match:
            return match.group(1)
    return ""


def parse_kind_detail(html: str, source_url: str, ir_seq: str = "") -> dict[str, Any] | None:
    """Parse one KIND IR detail page by its labels instead of fragile column offsets."""
    soup = BeautifulSoup(html, "html.parser")
    values: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = [clean_text(cell.get_text(" ")) for cell in row.find_all(["th", "td"])]
        if not cells:
            continue
        # Some rows contain several label/value pairs.
        for i, cell in enumerate(cells[:-1]):
            label = re.sub(r"\s+", "", cell)
            if label in {"회사명", "일자", "시간", "제목", "내용", "시장구분", "URL"}:
                values[label] = cells[i + 1]
    text = clean_text(soup.get_text(" "))
    company = clean_text(values.get("회사명"))
    title_raw = clean_text(values.get("제목"))
    content = clean_text(values.get("내용"))
    date_raw = clean_text(values.get("일자"))
    time_raw = clean_text(values.get("시간"))
    if not company:
        match = re.search(r"회사명\s+(.{1,80}?)\s+시장구분", text)
        if match:
            company = clean_text(match.group(1))
    if not date_raw:
        match = re.search(r"일자\s+(20\d{2}[-./]\d{1,2}[-./]\d{1,2})", text)
        if match:
            date_raw = match.group(1)
    if not time_raw:
        match = re.search(r"시간\s+(--:--|\d{1,2}:\d{2})", text)
        if match:
            time_raw = match.group(1)
    if not title_raw:
        match = re.search(r"제목\s+(.{2,180}?)(?=\s+내용\s+|$)", text)
        if match:
            title_raw = clean_text(match.group(1))
    if not content:
        match = re.search(r"내용\s+(.{2,400})", text)
        if match:
            content = clean_text(match.group(1))
    combined = f"{title_raw} {content}".lower()
    if not company or not any(k in combined for k in (
        "실적", "경영실적", "잠정", "earnings", "financial results",
        "results announcement", "results release", "conference call",
    )):
        return None
    d = parse_korean_date(date_raw)
    if not d:
        return None
    hour, minute, all_day = parse_korean_time(time_raw)
    title = koreanize_earnings_title(title_raw or content or "실적 발표", d.year)
    compact_company = re.sub(r"\s+", "", company)
    when = datetime(d.year, d.month, d.day, hour, minute, tzinfo=KST)
    return event(
        event_id=f"kr-earnings-{stable_id(compact_company)}-{d.isoformat()}",
        title=f"{company} {title}",
        when=when,
        source_key="kind",
        source=SOURCE_LABELS["kind"],
        source_url=source_url,
        category="earnings",
        importance=kr_importance(company),
        market="KR",
        all_day=all_day,
        confidence="official_schedule_detail",
    )


def parse_kind_row(row: Any) -> dict[str, Any] | None:
    """Best-effort parser for a KIND list row when no detail identifier is exposed."""
    cells = [clean_text(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
    date_index = next((i for i, cell in enumerate(cells)
                       if re.fullmatch(r"20\d{2}[.-]\d{1,2}[.-]\d{1,2}", cell)), -1)
    if date_index < 0:
        return None
    d = parse_korean_date(cells[date_index])
    if not d:
        return None
    before = cells[:date_index]
    title_index = next((i for i in range(len(before) - 1, -1, -1)
                        if any(k in before[i].lower() for k in (
                            "실적", "경영실적", "잠정", "earnings", "financial results",
                            "results announcement", "results release", "conference call",
                        ))), -1)
    if title_index < 0:
        return None
    raw_title = before[title_index]
    company = ""
    for cell in reversed(before[:title_index]):
        candidate = re.sub(r"^(유가증권|코스닥|코넥스)\s*", "", cell).strip()
        if not candidate or candidate.isdigit() or candidate in {"-", "보기"}:
            continue
        if len(candidate) <= 80:
            company = candidate
            break
    if not company:
        return None
    time_text = cells[date_index + 1] if date_index + 1 < len(cells) else ""
    hour, minute, all_day = parse_korean_time(time_text)
    title = koreanize_earnings_title(raw_title, d.year)
    compact_company = re.sub(r"\s+", "", company)
    link = row.find("a", href=True)
    source_url = urljoin(KIND_IR, link["href"]) if link else KIND_IR
    return event(
        event_id=f"kr-earnings-{stable_id(compact_company)}-{d.isoformat()}",
        title=f"{company} {title}",
        when=datetime(d.year, d.month, d.day, hour, minute, tzinfo=KST),
        source_key="kind",
        source=SOURCE_LABELS["kind"],
        source_url=source_url,
        category="earnings",
        importance=kr_importance(company),
        market="KR",
        all_day=all_day,
        confidence="official_schedule_list",
    )


def collect_kind(config: dict[str, Any] | None = None, state: dict[str, Any] | None = None, force: bool = False) -> SourceResult:
    """Collect all earnings-related KIND IR schedules with detail-page verification.

    The collector does not use a company allowlist. It combines the list view, the
    current-month calendar view and the official detail pages. Detail pages are cached
    by irSeq so normal 30-minute runs only download newly registered schedules.
    """
    state = state if state is not None else {}
    if int(state.get("kindDetailParserVersion") or 0) != KIND_DETAIL_PARSER_VERSION:
        state["kindDetailCache"] = {}
        state["kindDetailParserVersion"] = KIND_DETAIL_PARSER_VERSION
    cache = state.setdefault("kindDetailCache", {})
    out_by_id: dict[str, dict[str, Any]] = {}
    seen_sequences: set[str] = set()
    seen_pages: set[str] = set()
    page_htmls: list[str] = []

    # The current-month calendar is an independent path and catches schedules that a
    # list-page pagination change might otherwise hide (Samsung Electronics was one).
    try:
        page_htmls.append(http_get(KIND_IR_CALENDAR).text)
    except Exception:
        pass

    empty_pages = 0
    for page in range(1, 40):
        base = {
            "gubun": "iRSchedule",
            "method": "searchIRScheduleMain",
            "pageIndex": str(page),
            "pageNo": str(page),
            "currentPage": str(page),
            "currentPageSize": "100",
        }
        candidates: list[str] = []
        for request in (
            lambda: http_post(KIND_IR, data=base).text,
            lambda: http_get(KIND_IR, params=base).text,
        ):
            try:
                candidates.append(request())
            except Exception:
                continue
        if not candidates:
            break
        # Prefer the response exposing the largest number of detail references/rows.
        html = max(candidates, key=lambda x: (len(re.findall(r"irSeq|searchIRSchedule(?:Detail|Popup)", x, re.I)), len(x)))
        fingerprint = stable_id(re.sub(r"\s+", " ", html[:100000]))
        if page > 1 and fingerprint in seen_pages:
            break
        seen_pages.add(fingerprint)
        page_htmls.append(html)
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table tbody tr") or soup.find_all("tr")
        page_found = 0
        for row in rows:
            seq = kind_detail_seq(row)
            if seq:
                seen_sequences.add(seq)
                page_found += 1
            row_item = parse_kind_row(row)
            if row_item:
                old = out_by_id.get(row_item["id"])
                if old is None or event_score(row_item) >= event_score(old):
                    out_by_id[row_item["id"]] = row_item
                page_found += 1
        empty_pages = empty_pages + 1 if page_found == 0 else 0
        if page > 1 and empty_pages >= 2:
            break

    # Calendar/list HTML may expose links outside standard table rows.
    for html in page_htmls:
        seen_sequences.update(kind_detail_sequences(html))

    downloaded = 0
    detail_errors = 0
    for seq in sorted(seen_sequences, key=lambda x: int(x), reverse=True):
        detail_url = f"https://kind.krx.co.kr/corpgeneral/irschedule.do?irSeq={seq}&method=searchIRScheduleDetail"
        cached = cache.get(seq)
        item = None
        if (isinstance(cached, dict) and int(cached.get("parserVersion") or 0) == KIND_DETAIL_PARSER_VERSION
                and not cached.get("error") and not force):
            item = cached.get("event")
        else:
            try:
                html = http_get(detail_url, timeout=40).text
                item = parse_kind_detail(html, detail_url, seq)
                cache[seq] = {"checkedAt": iso_utc(), "parserVersion": KIND_DETAIL_PARSER_VERSION, "event": item}
                downloaded += 1
                time.sleep(0.03)
            except Exception as exc:
                detail_errors += 1
                cache[seq] = {"checkedAt": iso_utc(), "parserVersion": KIND_DETAIL_PARSER_VERSION, "event": None, "error": str(exc)[:180]}
                continue
        if item:
            old = out_by_id.get(item["id"])
            if old is None or event_score(item) >= event_score(old):
                out_by_id[item["id"]] = item

    # Keep the detail cache bounded; irSeq values are monotonic, so the newest entries
    # are the useful ones for schedule discovery.
    if len(cache) > 1200:
        for key in sorted(cache, key=lambda x: int(x) if str(x).isdigit() else 0)[:-1000]:
            cache.pop(key, None)

    out = list(out_by_id.values())
    if not out:
        raise RuntimeError("KIND 전체 실적 일정이 비어 있음")
    message = f"목록·달력 검증 · 상세번호 {len(seen_sequences)}건 · 실적 일정 {len(out)}개 · 새 상세 {downloaded}건"
    if detail_errors:
        message += f" · 상세 오류 {detail_errors}건"
    return SourceResult("kind", out, True, message)


def parse_official_ir_page(company: str, symbol: str, url: str, html: str) -> list[dict[str, Any]]:
    """Generic fallback parser for a company's official IR events page."""
    text = clean_text(BeautifulSoup(html, "html.parser").get_text(" "))
    out: dict[str, dict[str, Any]] = {}
    date_matches = list(re.finditer(r"(?:20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|20\d{2}[-./]\d{1,2}[-./]\d{1,2})", text))
    for match in date_matches:
        d = parse_korean_date(match.group(0))
        if not d:
            continue
        # 기업 공시 페이지에는 등록일·결정일·자료 게시일도 함께 표시된다.
        # 실제 실적 발표일이 아닌 관리용 날짜는 일정으로 만들지 않는다.
        prefix = text[max(0, match.start() - 60):match.start()].lower()
        if any(label in prefix for label in (
            "registration date", "decision date", "publication date",
            "등록일", "결정일자", "게재일시", "공시일", "작성일",
        )):
            continue
        context = text[max(0, match.start() - 220):match.end() + 220]
        low = context.lower()
        if not any(k in low for k in ("실적발표", "실적 발표", "earnings conference", "earnings call", "earnings release", "business results")):
            continue
        hour, minute, all_day = parse_korean_time(context)
        quarter = ""
        qmatch = re.search(r"(20\d{2}년\s*)?(\d)\s*(?:/4)?분기", context)
        if qmatch:
            quarter = f"{qmatch.group(1) or ''}{qmatch.group(2)}분기 "
        else:
            ematch = re.search(r"\bQ([1-4])\s*(?:FY)?\s*(20\d{2})\b", context, re.I)
            if ematch:
                quarter = f"{ematch.group(2)}년 {ematch.group(1)}분기 "
        title = f"{company} {quarter}실적 발표".replace("  ", " ")
        item = event(
            event_id=f"kr-earnings-{stable_id(re.sub(r'\\s+', '', company))}-{d.isoformat()}",
            title=title,
            when=datetime(d.year, d.month, d.day, hour, minute, tzinfo=KST),
            source_key="official_ir",
            source=SOURCE_LABELS["official_ir"],
            source_url=url,
            category="earnings",
            importance=kr_importance(company),
            symbol=symbol,
            market="KR",
            all_day=all_day,
            confidence="company_official_ir",
        )
        out[item["id"]] = item
    return list(out.values())


def collect_official_ir_pages(config: dict[str, Any]) -> SourceResult:
    """Supplement market-wide sources with configured official company IR pages.

    This is a fallback, not an allowlist: KIND and OpenDART still collect every company.
    """
    out: list[dict[str, Any]] = []
    pages = config.get("officialIrPages") or []
    errors = 0
    for item in pages:
        company = clean_text(item.get("company"))
        symbol = clean_text(item.get("symbol"))
        url = clean_text(item.get("url"))
        if not company or not url:
            continue
        try:
            out.extend(parse_official_ir_page(company, symbol, url, http_get(url, timeout=40).text))
        except Exception:
            errors += 1
    if pages and not out:
        return SourceResult("official_ir", [], False, f"공식 IR 페이지 {len(pages)}곳에서 일정을 찾지 못함")
    message = f"공식 IR 페이지 {len(pages)}곳 · 일정 {len(out)}개"
    if errors:
        message += f" · 오류 {errors}곳"
    return SourceResult("official_ir", out, True, message)


def decode_document_bytes(raw: bytes) -> str:
    """Decode one DART original-document member without assuming one encoding."""
    for encoding in ("utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def extract_dart_document_text(payload: bytes) -> str:
    """Extract searchable text from OpenDART's ZIP original-document response."""
    if payload[:1] in (b"{", b"<") and b"PK" not in payload[:8]:
        preview = decode_document_bytes(payload[:1000])
        if "status" in preview and "message" in preview:
            raise RuntimeError(clean_text(BeautifulSoup(preview, "html.parser").get_text(" ")))
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("OpenDART 원문 ZIP 형식이 아님") from exc
    chunks: list[str] = []
    members = sorted(
        (info for info in archive.infolist() if not info.is_dir()),
        key=lambda info: info.file_size,
        reverse=True,
    )
    for info in members[:12]:
        if info.file_size <= 0:
            continue
        raw = archive.read(info)
        decoded = decode_document_bytes(raw)
        soup = BeautifulSoup(decoded, "html.parser")
        text = clean_text(html_lib.unescape(soup.get_text(" ")))
        if text:
            chunks.append(text)
    return clean_text(" ".join(chunks))


def parse_korean_date(value: str) -> date | None:
    compact = re.fullmatch(r"(20\d{2})(\d{2})(\d{2})", value.strip())
    if compact:
        try:
            return date(int(compact.group(1)), int(compact.group(2)), int(compact.group(3)))
        except ValueError:
            return None
    match = re.search(r"(20\d{2})\s*(?:년|[-./])\s*(\d{1,2})\s*(?:월|[-./])\s*(\d{1,2})\s*일?", value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_korean_time(value: str) -> tuple[int, int, bool]:
    if "--:--" in value or "시간 미정" in value:
        return 12, 0, True
    match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", value)
    if match:
        return int(match.group(1)), int(match.group(2)), False
    match = re.search(r"(오전|오후)?\s*(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?", value)
    if match:
        hour = int(match.group(2))
        minute = int(match.group(3) or 0)
        if match.group(1) == "오후" and hour < 12:
            hour += 12
        if match.group(1) == "오전" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute, False
    return 12, 0, True



def is_earnings_schedule_report(report_name: str) -> bool:
    """Return True for exchange filings that can announce an earnings date.

    This intentionally works by filing type, not by company name.  It covers both
    IR-event notices and settlement-results preview notices for every listed company.
    """
    compact = re.sub(r"\s+", "", clean_text(report_name)).lower()
    return any(token in compact for token in (
        "기업설명회(ir)개최",
        "기업설명회(ir)개최(안내공시)",
        "기업설명회개최",
        "결산실적공시예고",
        "실적공시예고",
        "earningsrelease",
        "organizationofinvestorrelationsevent",
    ))


def extract_kind_external_urls(html: str, base_url: str) -> list[str]:
    """Find official KRX/KIND external disclosure documents embedded in DART.

    DART exchange filings often render the original KRX document in an iframe or a
    JavaScript string.  The URL can be plain, protocol-relative, HTML-escaped or URL
    encoded, so inspect both DOM attributes and decoded source text.
    """
    decoded = unquote(html_lib.unescape(html or ""))
    candidates: list[str] = []
    soup = BeautifulSoup(decoded, "html.parser")
    for node in soup.find_all(True):
        for attr in ("href", "src", "data", "data-src", "value", "onclick"):
            value = node.get(attr)
            if isinstance(value, list):
                value = " ".join(str(x) for x in value)
            if value:
                candidates.append(str(value))
    candidates.append(decoded)

    found: list[str] = []
    seen: set[str] = set()
    patterns = (
        r"https?://kind\.krx\.co\.kr/external/[^\"'<>\s)]+?\.html?",
        r"//kind\.krx\.co\.kr/external/[^\"'<>\s)]+?\.html?",
        r"/external/20\d{2}/[^\"'<>\s)]+?\.html?",
    )
    for blob in candidates:
        blob = unquote(html_lib.unescape(blob))
        for pattern in patterns:
            for match in re.findall(pattern, blob, re.I):
                if match.startswith("//"):
                    url = "https:" + match
                elif match.startswith("/external/"):
                    url = "https://kind.krx.co.kr" + match
                else:
                    url = urljoin(base_url, match)
                url = url.replace("&amp;", "&")
                if url not in seen:
                    seen.add(url)
                    found.append(url)
    return found


def public_filing_text(html: str) -> str:
    """Preserve useful table labels while flattening a public disclosure page."""
    soup = BeautifulSoup(html or "", "html.parser")
    chunks: list[str] = []
    for row in soup.find_all("tr"):
        cells = [clean_text(cell.get_text(" ")) for cell in row.find_all(["th", "td"])]
        if cells:
            chunks.append(" | ".join(cells))
    page_text = clean_text(soup.get_text(" "))
    if page_text:
        chunks.append(page_text)
    return clean_text(" \n ".join(chunks))


def parse_dart_public_fallback(
    *,
    corp_name: str,
    stock_code: str,
    receipt_no: str,
    receipt_date: date,
    report_name: str,
) -> tuple[dict[str, Any] | None, str]:
    """Parse the public DART/KRX HTML when the OpenDART ZIP loses table structure.

    The discovery step still comes from the market-wide OpenDART list, so this applies
    to every company.  No company-specific IR URL or allowlist is used.
    """
    view_url = f"{DART_PUBLIC_VIEW}?rcpNo={receipt_no}"
    response = http_get(view_url, timeout=45)
    main_html = response.text

    # Some DART pages already contain enough visible text to parse directly.
    item = extract_ir_schedule_from_document(
        text=public_filing_text(main_html),
        corp_name=corp_name,
        stock_code=stock_code,
        receipt_no=receipt_no,
        receipt_date=receipt_date,
        report_name=report_name,
        source_url=view_url,
        confidence="official_dart_html",
    )
    if item:
        return item, "dart_html"

    # Exchange disclosures commonly embed the original KIND document.
    for external_url in extract_kind_external_urls(main_html, view_url):
        try:
            external_html = http_get(external_url, timeout=45).text
        except Exception:
            continue
        item = extract_ir_schedule_from_document(
            text=public_filing_text(external_html),
            corp_name=corp_name,
            stock_code=stock_code,
            receipt_no=receipt_no,
            receipt_date=receipt_date,
            report_name=report_name,
            source_url=external_url,
            confidence="official_krx_html",
        )
        if item:
            return item, "kind_external"
    return None, ""


def extract_ir_schedule_from_document(
    *,
    text: str,
    corp_name: str,
    stock_code: str,
    receipt_no: str,
    receipt_date: date,
    report_name: str = "",
    source_url: str = "",
    confidence: str = "official_filing",
) -> dict[str, Any] | None:
    """Parse an official market-wide filing into one earnings schedule event.

    There is deliberately no company allowlist. Every listed company is accepted when
    the filing type or body says the event is about earnings/results.
    """
    normalized = clean_text(text)
    low = normalized.lower()
    earnings_terms = (
        "경영실적", "실적발표", "실적 발표", "잠정실적", "결산실적",
        "공시예정일", "공시예고", "earnings", "financial results",
        "results announcement", "results release",
    )
    report_low = re.sub(r"\s+", "", clean_text(report_name)).lower()
    preview_notice = "결산실적공시예고" in report_low or "실적공시예고" in report_low
    if not any(term in low for term in earnings_terms) and not preview_notice:
        return None

    # Prefer the date immediately following an event/preview-date label. Public KRX
    # HTML is flattened with "|" separators, while OpenDART ZIP text is mostly spaces.
    date_candidates: list[tuple[int, date]] = []
    labeled_patterns = (
        r"(?:행사일|개최일|시작일|개최일자|공시예정일|결산실적\s*공시예정일|예정일|일시(?:\s*및\s*장소)?)\s*[:：|]?\s*(.{0,260})",
        r"(?:date\s*&\s*time|date\s+and\s+time)\s*[:：|]?\s*(.{0,260})",
    )
    for pattern in labeled_patterns:
        for match in re.finditer(pattern, normalized, re.I):
            window = match.group(1)
            parsed = parse_korean_date(window)
            if parsed:
                date_candidates.append((0, parsed))

    # Fall back to every date in the document, but penalize administrative dates.
    for match in re.finditer(r"20\d{2}\s*(?:년|[-./])\s*\d{1,2}\s*(?:월|[-./])\s*\d{1,2}\s*일?", normalized):
        parsed = parse_korean_date(match.group(0))
        if not parsed:
            continue
        context = normalized[max(0, match.start() - 70):match.start()].lower()
        penalty = 4 if any(label in context for label in (
            "결정일자", "decision date", "공시일", "작성일", "등록일",
            "registration date", "게재일시", "publication date",
        )) else 1
        date_candidates.append((penalty, parsed))

    valid = [item for item in date_candidates if receipt_date - timedelta(days=2) <= item[1] <= receipt_date + timedelta(days=240)]
    if not valid:
        return None
    valid.sort(key=lambda item: (item[0], 0 if item[1] >= receipt_date else 1, item[1]))
    event_date = valid[0][1]

    # Read time next to the selected date first, then use explicit time labels.
    date_tokens = [
        event_date.strftime("%Y-%m-%d"),
        event_date.strftime("%Y.%m.%d"),
        f"{event_date.year}년 {event_date.month}월 {event_date.day}일",
    ]
    time_context = normalized
    for token in date_tokens:
        pos = normalized.find(token)
        if pos >= 0:
            time_context = normalized[pos:pos + 300]
            break
    hour, minute, all_day = parse_korean_time(time_context)
    if all_day:
        for pattern in (
            r"(?:공시예정시간|예정시간|개최시각|시간|date\s*&\s*time)\s*[:：|]?\s*(.{0,120})",
            r"(?:일시|개최일자).{0,100}?((?:[01]?\d|2[0-3]):[0-5]\d)",
        ):
            match = re.search(pattern, normalized, re.I)
            if match:
                hour, minute, all_day = parse_korean_time(match.group(1))
                if not all_day:
                    break

    # Prefer the official purpose/content text as the title fragment.
    title_fragment = "실적 발표"
    title_patterns = (
        r"(?:개최목적|실시목적|purpose\s+of\s+ir)\s*[:：|]?\s*(.{3,180}?)(?=개최방법|실시방법|method\s+of\s+ir|주요\s*설명회내용|주요내용|summary\s+of\s+key|ir\s*자료|\d+\.)",
        r"(?:주요\s*설명회내용(?:\(요약\))?|주요내용|summary\s+of\s+key\s+topics[^|]*)\s*[:：|]?\s*(.{3,180}?)(?=ir\s*자료|기타\s*투자판단|후원기관|\d+\.)",
        r"((?:20\d{2}년\s*)?(?:\d분기|상반기|하반기|연간)?\s*(?:경영)?실적\s*(?:발표|설명회|설명))",
        r"(q[1-4]\s*(?:fy)?\s*20\d{2}\s*earnings\s*release)",
    )
    for pattern in title_patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            candidate = clean_text(match.group(1))
            if any(term in candidate.lower() for term in earnings_terms):
                title_fragment = candidate[:100]
                break
    title_fragment = koreanize_earnings_title(title_fragment, event_date.year)
    compact_company = re.sub(r"\s+", "", corp_name)
    when = datetime(event_date.year, event_date.month, event_date.day, hour, minute, tzinfo=KST)
    return event(
        event_id=f"kr-earnings-{stable_id(compact_company)}-{event_date.isoformat()}",
        title=f"{corp_name} {title_fragment}",
        when=when,
        source_key="dart_schedule",
        source=SOURCE_LABELS["dart_schedule"],
        source_url=source_url or f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}",
        category="earnings",
        importance=kr_importance(corp_name),
        symbol=stock_code,
        market="KR",
        all_day=all_day,
        confidence=confidence,
    )

def collect_dart_schedules(api_key: str, state: dict[str, Any], force: bool) -> SourceResult:
    """Discover earnings schedules for all KOSPI/KOSDAQ/KONEX companies.

    Primary discovery is the OpenDART exchange-disclosure list. Each new IR filing is
    downloaded through the official original-document API and parsed for event date/time.
    Cached parsed filings keep the 30-minute workflow well below free API limits.
    """
    if not api_key:
        return SourceResult("dart_schedule", [], False, "OpenDART 인증키 미설정")
    today = NOW.astimezone(KST).date()
    # OpenDART는 corp_code 없이 조회할 때 검색기간을 최대 3개월로 제한한다.
    begin = (today - timedelta(days=89)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    filings: list[dict[str, Any]] = []
    page = 1
    while page <= 100:
        params = {
            "crtfc_key": api_key,
            "bgn_de": begin,
            "end_de": end,
            "last_reprt_at": "N",
            "pblntf_ty": "I",
            "page_no": page,
            "page_count": 100,
            "sort": "date",
            "sort_mth": "desc",
        }
        payload = http_get(DART_LIST, params=params).json()
        status = payload.get("status")
        if status == "013":
            break
        if status not in ("000", None):
            raise RuntimeError(payload.get("message", f"DART status {status}"))
        rows = payload.get("list") or []
        for row in rows:
            report = clean_text(row.get("report_nm"))
            if not is_earnings_schedule_report(report):
                continue
            filings.append(row)
        total_page = int(payload.get("total_page") or 1)
        if page >= total_page:
            break
        page += 1

    # 이전 버전에서 잘못 저장된 '파싱 실패(None)' 캐시를 자동 폐기한다.
    # 사용자가 별도의 force_refresh 옵션을 찾거나 누를 필요가 없다.
    if int(state.get("dartIrParserVersion") or 0) != DART_IR_PARSER_VERSION:
        state["dartIrScheduleCache"] = {}
        state["dartIrParserVersion"] = DART_IR_PARSER_VERSION
    cache = state.setdefault("dartIrScheduleCache", {})
    out_by_id: dict[str, dict[str, Any]] = {}
    downloaded = 0
    public_fallbacks = 0
    public_fallback_hits = 0
    parse_failed = 0
    for row in filings:
        receipt_no = clean_text(row.get("rcept_no"))
        corp_name = clean_text(row.get("corp_name"))
        stock_code = clean_text(row.get("stock_code"))
        receipt_raw = clean_text(row.get("rcept_dt"))
        if not receipt_no or not corp_name:
            continue
        try:
            receipt_date = datetime.strptime(receipt_raw, "%Y%m%d").date()
        except ValueError:
            receipt_date = today
        cached = cache.get(receipt_no)
        parsed_event: dict[str, Any] | None = None
        cache_is_current = (
            isinstance(cached, dict)
            and int(cached.get("parserVersion") or 0) == DART_IR_PARSER_VERSION
            and "event" in cached
            and not cached.get("error")
        )
        if cache_is_current and not force:
            parsed_event = cached.get("event")
        else:
            method = ""
            errors: list[str] = []
            try:
                response = http_get(DART_DOCUMENT, params={"crtfc_key": api_key, "rcept_no": receipt_no}, timeout=60)
                text = extract_dart_document_text(response.content)
                parsed_event = extract_ir_schedule_from_document(
                    text=text,
                    corp_name=corp_name,
                    stock_code=stock_code,
                    receipt_no=receipt_no,
                    receipt_date=receipt_date,
                    report_name=clean_text(row.get("report_nm")),
                )
                method = "opendart_zip" if parsed_event else ""
                downloaded += 1
            except Exception as exc:
                errors.append(f"zip: {exc}")

            # The exact KRX public document used for Samsung Electro-Mechanics is a
            # fallback for every filing, not a company-specific exception.
            if parsed_event is None:
                public_fallbacks += 1
                try:
                    parsed_event, method = parse_dart_public_fallback(
                        corp_name=corp_name,
                        stock_code=stock_code,
                        receipt_no=receipt_no,
                        receipt_date=receipt_date,
                        report_name=clean_text(row.get("report_nm")),
                    )
                    if parsed_event:
                        public_fallback_hits += 1
                except Exception as exc:
                    errors.append(f"public: {exc}")

            cache[receipt_no] = {
                "checkedAt": iso_utc(),
                "receiptDate": receipt_raw,
                "parserVersion": DART_IR_PARSER_VERSION,
                "reportName": clean_text(row.get("report_nm")),
                "method": method,
                "event": parsed_event,
            }
            if parsed_event is None and errors:
                parse_failed += 1
                cache[receipt_no]["error"] = " | ".join(errors)[:300]
            time.sleep(0.05)
        if parsed_event:
            current = out_by_id.get(parsed_event["id"])
            if current is None or event_score(parsed_event) >= event_score(current):
                out_by_id[parsed_event["id"]] = parsed_event

    # Prune old cache entries so state.json does not grow forever.
    cutoff = today - timedelta(days=200)
    for receipt_no in list(cache):
        cached_date = parse_korean_date(str(cache[receipt_no].get("receiptDate", "")))
        if cached_date and cached_date < cutoff:
            cache.pop(receipt_no, None)
    out = list(out_by_id.values())
    if filings and not out:
        raise RuntimeError(f"IR 공시 {len(filings)}건을 찾았지만 실적 일정 파싱 결과가 0건")
    message = (
        f"실적 일정 공시 {len(filings)}건 · 일정 {len(out)}개 · OpenDART 원문 {downloaded}건"
        f" · 공개문서 보완 {public_fallback_hits}/{public_fallbacks}건 · 파서 v{DART_IR_PARSER_VERSION}"
    )
    if parse_failed:
        message += f" · 원문 오류 {parse_failed}건"
    return SourceResult("dart_schedule", out, True, message)


def collect_nasdaq_earnings(state: dict[str, Any], force: bool) -> SourceResult:
    """Free no-key fallback for the full U.S. earnings calendar on Nasdaq's domain."""
    previous_events = load_json(EVENTS_FILE, {}).get("events", [])
    last = parse_iso(state.get("nasdaqCalendarCheckedAt"))
    if not force and last and NOW - last < timedelta(hours=20):
        cached = [item for item in previous_events if item.get("sourceKey") == "nasdaq" and item.get("status") == "scheduled"]
        return SourceResult("nasdaq", cached, True, f"이전 전체 달력 유지 {len(cached)}개")
    today_et = NOW.astimezone(ET).date()
    out: list[dict[str, Any]] = []
    for offset in range(0, 46):
        d = today_et + timedelta(days=offset)
        response = http_get(NASDAQ_EARNINGS, params={"date": d.isoformat()}, timeout=30)
        payload = response.json()
        rows = (((payload.get("data") or {}).get("rows")) or [])
        for raw in rows:
            symbol = clean_text(raw.get("symbol")).upper()
            if not symbol:
                continue
            raw_name = clean_text(raw.get("name"))
            market_cap = parse_market_cap(raw.get("marketCap"))
            timing_raw = clean_text(raw.get("time")).lower()
            if "after" in timing_raw:
                hour, all_day, timing = 16, False, "미국 장 마감 후"
            elif "before" in timing_raw or "pre" in timing_raw:
                hour, all_day, timing = 8, False, "미국 장 시작 전"
            else:
                hour, all_day, timing = 12, True, "발표 시간 미정"
            expected = clean_text(raw.get("epsForecast"))
            fiscal = clean_text(raw.get("fiscalQuarterEnding"))
            summary = timing
            if expected and expected not in ("N/A", "--"):
                summary += f" · 예상 EPS {expected}"
            if fiscal:
                summary += f" · 회계기간 {fiscal}"
            when = datetime(d.year, d.month, d.day, hour, 0, tzinfo=ET)
            out.append(event(
                event_id=f"us-earnings-{symbol}-{d.isoformat()}",
                title=f"{company_display_name(symbol, raw_name)} 실적 발표",
                when=when,
                source_key="nasdaq",
                source=SOURCE_LABELS["nasdaq"],
                source_url=f"https://www.nasdaq.com/market-activity/earnings?date={d.isoformat()}",
                category="earnings",
                importance=us_importance(symbol, market_cap),
                summary=summary,
                symbol=symbol,
                market="US",
                expected="" if expected in ("N/A", "--") else expected,
                all_day=all_day,
                official=False,
                confidence="exchange_calendar",
            ))
        time.sleep(0.03)
    state["nasdaqCalendarCheckedAt"] = iso_utc()
    return SourceResult("nasdaq", out, True, f"향후 45일 전체 실적 {len(out)}개")


def extract_dart_document_parts(payload: bytes) -> tuple[str, list[list[str]]]:
    """Return flattened text and table rows from an OpenDART original-document ZIP."""
    if payload[:1] in (b"{", b"<") and b"PK" not in payload[:8]:
        preview = decode_document_bytes(payload[:2000])
        if "status" in preview and "message" in preview:
            raise RuntimeError(clean_text(BeautifulSoup(preview, "html.parser").get_text(" ")))
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("OpenDART 원문 ZIP 형식이 아님") from exc
    text_chunks: list[str] = []
    rows: list[list[str]] = []
    members = sorted(
        (info for info in archive.infolist() if not info.is_dir()),
        key=lambda info: info.file_size,
        reverse=True,
    )
    for info in members[:16]:
        if info.file_size <= 0:
            continue
        decoded = decode_document_bytes(archive.read(info))
        soup = BeautifulSoup(decoded, "html.parser")
        text = clean_text(html_lib.unescape(soup.get_text(" ")))
        if text:
            text_chunks.append(text)
        for tr in soup.find_all("tr"):
            cells = [clean_text(html_lib.unescape(td.get_text(" "))) for td in tr.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if len(cells) >= 2:
                rows.append(cells)
    return clean_text(" ".join(text_chunks)), rows


def parse_number(value: Any) -> float | None:
    text = clean_text(value)
    if not text or text in {"-", "--", "N/A", "해당없음"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if not text or text in {"-", "."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return -abs(number) if negative else number


def detect_krw_multiplier(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    if "단위:억원" in compact or "단위：억원" in compact:
        return 100_000_000.0
    if "단위:백만원" in compact or "단위：백만원" in compact:
        return 1_000_000.0
    if "단위:천원" in compact or "단위：천원" in compact:
        return 1_000.0
    if "단위:원" in compact or "단위：원" in compact:
        return 1.0
    # Most tentative-results filings use KRW millions when the unit is near the table.
    if "백만원" in compact[:1200]:
        return 1_000_000.0
    if "억원" in compact[:1200]:
        return 100_000_000.0
    return 1.0


def format_krw(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 1_000_000_000_000:
        jo = amount / 1_000_000_000_000
        return f"{sign}{jo:.2f}조 원".replace(".00", "")
    if amount >= 100_000_000:
        eok = amount / 100_000_000
        return f"{sign}{eok:,.1f}억 원".replace(".0억", "억")
    if amount >= 10_000:
        man = amount / 10_000
        return f"{sign}{man:,.1f}만 원".replace(".0만", "만")
    return f"{sign}{amount:,.0f}원"


def format_usd(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 1_000_000_000_000:
        return f"{sign}{amount / 1_000_000_000_000:.2f}조 달러".replace(".00", "")
    if amount >= 100_000_000:
        return f"{sign}{amount / 100_000_000:,.1f}억 달러".replace(".0억", "억")
    if amount >= 10_000:
        return f"{sign}{amount / 10_000:,.1f}만 달러".replace(".0만", "만")
    return f"{sign}{amount:,.0f}달러"


def pct_change(actual: float | None, previous: float | None) -> float | None:
    if actual is None or previous in (None, 0):
        return None
    return (actual - previous) / abs(previous) * 100


def result_rating(primary_pct: float | None, secondary_pct: float | None = None) -> int:
    pct = primary_pct if primary_pct is not None else secondary_pct
    if pct is None:
        return 0
    if pct >= 10:
        return 2
    if pct > 0:
        return 1
    if pct <= -10:
        return -2
    if pct < 0:
        return -1
    return 0


KR_RESULT_METRICS = {
    "revenue": ("매출액", "영업수익", "수익(매출액)", "매출"),
    "operating": ("영업이익", "영업손실"),
    "net": ("당기순이익", "분기순이익", "반기순이익", "연결당기순이익", "순이익"),
}


def row_metric_values(rows: list[list[str]], aliases: tuple[str, ...], multiplier: float) -> tuple[float | None, float | None, float | None]:
    """Parse actual, previous quarter and prior-year values from a tentative-results row."""
    best: tuple[int, tuple[float | None, float | None, float | None]] | None = None
    for cells in rows:
        joined = " ".join(cells)
        compact = re.sub(r"\s+", "", joined)
        if not any(alias in compact for alias in aliases):
            continue
        numbers: list[float] = []
        for cell in cells:
            # Ignore percentages and dates. Amount columns are plain numbers.
            if "%" in cell or re.search(r"20\d{2}[./-]\d{1,2}", cell):
                continue
            value = parse_number(cell)
            if value is not None:
                numbers.append(value * multiplier)
        if not numbers:
            continue
        # In standard DART tables: actual, previous quarter, previous-year quarter.
        actual = numbers[0]
        previous_q = numbers[1] if len(numbers) >= 2 else None
        previous_y = numbers[2] if len(numbers) >= 3 else previous_q
        score = (3 if "당해실적" in compact else 0) + min(len(numbers), 3)
        candidate = (actual, previous_q, previous_y)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else (None, None, None)


def financial_metric_from_rows(rows: list[dict[str, Any]], aliases: tuple[str, ...]) -> tuple[float | None, float | None, str]:
    candidates: list[tuple[int, float | None, float | None, str]] = []
    for row in rows:
        account = clean_text(row.get("account_nm"))
        account_compact = re.sub(r"\s+", "", account)
        if not any(alias in account_compact for alias in aliases):
            continue
        sj = clean_text(row.get("sj_div"))
        if sj not in {"IS", "CIS"}:
            continue
        actual = parse_number(row.get("thstrm_amount"))
        previous = parse_number(row.get("frmtrm_q_amount") or row.get("frmtrm_amount"))
        currency = clean_text(row.get("currency")) or "KRW"
        exact = 3 if account_compact in aliases else 1
        consolidated = 1 if clean_text(row.get("fs_div")) == "CFS" else 0
        candidates.append((exact + consolidated, actual, previous, currency))
    if not candidates:
        return None, None, "KRW"
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, actual, previous, currency = candidates[0]
    return actual, previous, currency


def report_financial_params(report: str, receipt_date: date) -> tuple[int, str] | None:
    year_match = re.search(r"\((20\d{2})[.\-/]", report)
    year = int(year_match.group(1)) if year_match else receipt_date.year
    if "1분기보고서" in report:
        return year, "11013"
    if "반기보고서" in report:
        return year, "11012"
    if "3분기보고서" in report:
        return year, "11014"
    if "사업보고서" in report:
        return year - 1 if not year_match else year, "11011"
    return None


def build_kr_result_event(
    *, corp_name: str, stock_code: str, receipt_no: str, receipt_date: date,
    report: str, revenue: float | None, revenue_prev: float | None,
    operating: float | None, operating_prev: float | None,
    net_income: float | None, net_prev: float | None,
) -> dict[str, Any]:
    operating_yoy = pct_change(operating, operating_prev)
    revenue_yoy = pct_change(revenue, revenue_prev)
    net_yoy = pct_change(net_income, net_prev)
    rating = result_rating(operating_yoy, revenue_yoy if revenue_yoy is not None else net_yoy)
    parts = [rating_text(rating)]
    if revenue is not None:
        text = f"매출 {format_krw(revenue)}"
        if revenue_yoy is not None:
            text += f" ({revenue_yoy:+.1f}%)"
        parts.append(text)
    if operating is not None:
        text = f"영업익 {format_krw(operating)}"
        if operating_yoy is not None:
            text += f" ({operating_yoy:+.1f}%)"
        parts.append(text)
    if net_income is not None:
        text = f"순익 {format_krw(net_income)}"
        if net_yoy is not None:
            text += f" ({net_yoy:+.1f}%)"
        parts.append(text)
    if len(parts) == 1:
        parts.append(f"{report} 공식 공시 확인")
    parts.append("예상치 없음")
    actual_parts = []
    if revenue is not None:
        actual_parts.append(f"매출 {format_krw(revenue)}")
    if operating is not None:
        actual_parts.append(f"영업익 {format_krw(operating)}")
    if net_income is not None:
        actual_parts.append(f"순익 {format_krw(net_income)}")
    previous_parts = []
    if revenue_prev is not None:
        previous_parts.append(f"매출 {format_krw(revenue_prev)}")
    if operating_prev is not None:
        previous_parts.append(f"영업익 {format_krw(operating_prev)}")
    if net_prev is not None:
        previous_parts.append(f"순익 {format_krw(net_prev)}")
    when = datetime(receipt_date.year, receipt_date.month, receipt_date.day, 18, 0, tzinfo=KST)
    period = infer_report_period(report, receipt_date)
    return event(
        event_id=f"kr-result-{stock_code or stable_id(corp_name)}-{period}",
        title=f"{corp_name} 실적 결과",
        when=when,
        source_key="dart",
        source=SOURCE_LABELS["dart"],
        source_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}",
        category="earnings",
        importance=kr_importance(corp_name),
        status="released",
        summary=" · ".join(parts),
        symbol=stock_code,
        market="KR",
        actual=", ".join(actual_parts),
        expected="",
        previous=", ".join(previous_parts),
        rating=rating,
        official=True,
        confidence="official_financials" if actual_parts else "official_filing",
    )


def parse_tentative_result_document(payload: bytes, *, corp_name: str, stock_code: str,
                                    receipt_no: str, receipt_date: date, report: str) -> dict[str, Any]:
    text, rows = extract_dart_document_parts(payload)
    multiplier = detect_krw_multiplier(text)
    revenue, _, revenue_prev = row_metric_values(rows, KR_RESULT_METRICS["revenue"], multiplier)
    operating, _, operating_prev = row_metric_values(rows, KR_RESULT_METRICS["operating"], multiplier)
    net_income, _, net_prev = row_metric_values(rows, KR_RESULT_METRICS["net"], multiplier)
    return build_kr_result_event(
        corp_name=corp_name, stock_code=stock_code, receipt_no=receipt_no,
        receipt_date=receipt_date, report=report, revenue=revenue,
        revenue_prev=revenue_prev, operating=operating,
        operating_prev=operating_prev, net_income=net_income, net_prev=net_prev,
    )


def fetch_periodic_result(api_key: str, *, corp_code: str, corp_name: str, stock_code: str,
                          receipt_no: str, receipt_date: date, report: str) -> dict[str, Any]:
    params = report_financial_params(report, receipt_date)
    if not params:
        raise RuntimeError("정기보고서 코드 판별 실패")
    year, report_code = params
    rows: list[dict[str, Any]] = []
    for fs_div in ("CFS", "OFS"):
        payload = http_get(DART_FINANCIAL, params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
            "fs_div": fs_div,
        }, timeout=40).json()
        status = payload.get("status")
        if status == "000" and payload.get("list"):
            rows = payload["list"]
            for row in rows:
                row["fs_div"] = fs_div
            break
        if status not in {"013", "000", None}:
            raise RuntimeError(payload.get("message", f"DART 재무제표 status {status}"))
    revenue, revenue_prev, _ = financial_metric_from_rows(rows, KR_RESULT_METRICS["revenue"])
    operating, operating_prev, _ = financial_metric_from_rows(rows, KR_RESULT_METRICS["operating"])
    net_income, net_prev, _ = financial_metric_from_rows(rows, KR_RESULT_METRICS["net"])
    return build_kr_result_event(
        corp_name=corp_name, stock_code=stock_code, receipt_no=receipt_no,
        receipt_date=receipt_date, report=report, revenue=revenue,
        revenue_prev=revenue_prev, operating=operating,
        operating_prev=operating_prev, net_income=net_income, net_prev=net_prev,
    )


def collect_dart(config: dict[str, Any] | None, api_key: str, state: dict[str, Any], force: bool) -> SourceResult:
    """Collect official Korean earnings results for every listed company.

    Tentative-results filings are parsed from the original document. Periodic reports
    use OpenDART's full-financial-statement endpoint. Results are cached by receipt
    number, and new filings are processed over successive 30-minute runs.
    """
    if not api_key:
        return SourceResult("dart", [], False, "OpenDART 인증키 미설정")
    today = NOW.astimezone(KST).date()
    begin = (today - timedelta(days=21)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    filings: list[dict[str, Any]] = []
    page = 1
    while page <= 30:
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
        if status == "013":
            break
        if status not in ("000", None):
            raise RuntimeError(payload.get("message", f"DART status {status}"))
        for row in payload.get("list") or []:
            report = clean_text(row.get("report_nm"))
            low = report.lower()
            is_result = any(k in low for k in (
                "잠정실적", "영업(잠정)실적", "영업실적", "매출액또는손익구조",
                "1분기보고서", "반기보고서", "3분기보고서", "사업보고서",
            ))
            if is_result and clean_text(row.get("stock_code")):
                filings.append(row)
        total_page = int(payload.get("total_page") or 1)
        if page >= total_page:
            break
        page += 1

    if int(state.get("dartResultParserVersion") or 0) != DART_RESULT_PARSER_VERSION:
        state["dartResultCache"] = {}
        state["dartResultParserVersion"] = DART_RESULT_PARSER_VERSION
    cache = state.setdefault("dartResultCache", {})
    previous_events = load_json(EVENTS_FILE, {}).get("events", [])
    out_by_id: dict[str, dict[str, Any]] = {
        item["id"]: item for item in previous_events
        if item.get("sourceKey") == "dart" and item.get("status") == "released" and item.get("id")
    }

    # Larger and market-moving companies are parsed first, but every company remains
    # eligible and is processed in later scheduled runs.
    filings.sort(key=lambda row: (
        -kr_importance(clean_text(row.get("corp_name"))),
        clean_text(row.get("rcept_dt")),
        clean_text(row.get("rcept_no")),
    ))
    processed_new = 0
    parse_errors = 0
    max_new_per_run = 80
    for row in filings:
        receipt = clean_text(row.get("rcept_no"))
        report = clean_text(row.get("report_nm"))
        corp_name = clean_text(row.get("corp_name"))
        stock_code = clean_text(row.get("stock_code"))
        corp_code = clean_text(row.get("corp_code"))
        receipt_raw = clean_text(row.get("rcept_dt"))
        if not receipt or not corp_name:
            continue
        try:
            receipt_date = datetime.strptime(receipt_raw, "%Y%m%d").date()
        except ValueError:
            receipt_date = today
        cached = cache.get(receipt)
        cache_current = (
            isinstance(cached, dict)
            and int(cached.get("parserVersion") or 0) == DART_RESULT_PARSER_VERSION
            and "event" in cached
            and not cached.get("error")
        )
        parsed: dict[str, Any] | None = cached.get("event") if cache_current and not force else None
        if parsed is None and (force or not cache_current):
            if processed_new >= max_new_per_run:
                continue
            try:
                if any(k in report for k in ("잠정실적", "영업(잠정)실적", "영업실적", "매출액또는손익구조")):
                    response = http_get(DART_DOCUMENT, params={"crtfc_key": api_key, "rcept_no": receipt}, timeout=60)
                    parsed = parse_tentative_result_document(
                        response.content,
                        corp_name=corp_name,
                        stock_code=stock_code,
                        receipt_no=receipt,
                        receipt_date=receipt_date,
                        report=report,
                    )
                else:
                    parsed = fetch_periodic_result(
                        api_key,
                        corp_code=corp_code,
                        corp_name=corp_name,
                        stock_code=stock_code,
                        receipt_no=receipt,
                        receipt_date=receipt_date,
                        report=report,
                    )
                cache[receipt] = {
                    "checkedAt": iso_utc(),
                    "receiptDate": receipt_raw,
                    "parserVersion": DART_RESULT_PARSER_VERSION,
                    "event": parsed,
                }
                processed_new += 1
                time.sleep(0.04)
            except Exception as exc:
                parse_errors += 1
                processed_new += 1
                cache[receipt] = {
                    "checkedAt": iso_utc(),
                    "receiptDate": receipt_raw,
                    "parserVersion": DART_RESULT_PARSER_VERSION,
                    "event": None,
                    "error": str(exc)[:240],
                }
                continue
        if parsed:
            out_by_id[parsed["id"]] = parsed

    cutoff = today - timedelta(days=150)
    for receipt in list(cache):
        cached_date = parse_korean_date(str(cache[receipt].get("receiptDate", "")))
        if cached_date and cached_date < cutoff:
            cache.pop(receipt, None)
    out = list(out_by_id.values())
    out.sort(key=lambda item: int(item.get("time", 0)))
    pending = sum(1 for row in filings if clean_text(row.get("rcept_no")) not in cache)
    message = f"결과 공시 {len(filings)}건 · 저장 결과 {len(out)}개 · 이번 분석 {processed_new}건"
    if pending:
        message += f" · 다음 실행 대기 {pending}건"
    if parse_errors:
        message += f" · 분석 오류 {parse_errors}건"
    return SourceResult("dart", out, True, message)

def infer_report_period(report: str, d: date) -> str:
    if "사업보고서" in report:
        return f"{d.year - 1}-FY"
    if "반기보고서" in report:
        return f"{d.year}-H1"
    if "분기보고서" in report:
        return f"{d.year}-Q{1 if d.month <= 5 else 3}"
    return d.isoformat()


def collect_alpha(config: dict[str, Any] | None, api_key: str, state: dict[str, Any], force: bool) -> SourceResult:
    """Collect the full U.S. earnings calendar without a watchlist."""
    if not api_key:
        return SourceResult("alpha", [], False, "미국 실적 데이터 인증키 미설정")
    previous_events = load_json(EVENTS_FILE, {}).get("events", [])
    out: list[dict[str, Any]] = []
    last = parse_iso(state.get("alphaCalendarCheckedAt"))
    should_calendar = force or not last or NOW - last >= timedelta(hours=22)
    if not should_calendar:
        cached = [item for item in previous_events if item.get("sourceKey") == "alpha" and item.get("status") == "scheduled"]
        return SourceResult("alpha", cached, True, f"이전 전체 달력 유지 {len(cached)}개")

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
        estimate = row.get("estimate", "") or row.get("estimatedEPS", "")
        fiscal = row.get("fiscalDateEnding", "")
        parts = [timing]
        if estimate:
            parts.append(f"예상 EPS {estimate}")
        if fiscal:
            parts.append(f"회계기간 {fiscal}")
        out.append(event(
            event_id=f"us-earnings-{symbol}-{d.isoformat()}",
            title=f"{company_display_name(symbol, row.get('name', ''))} 실적 발표",
            when=datetime(d.year, d.month, d.day, hour, 0, tzinfo=ET),
            source_key="alpha",
            source=SOURCE_LABELS["alpha"],
            source_url=f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&symbol={symbol}",
            category="earnings",
            importance=us_importance(symbol),
            summary=" · ".join(parts),
            symbol=symbol,
            market="US",
            expected=estimate,
            all_day=all_day,
            confidence="provider",
        ))
    state["alphaCalendarCheckedAt"] = iso_utc()
    return SourceResult("alpha", out, True, f"향후 3개월 전체 실적 {len(out)}개")


def sec_headers() -> dict[str, str]:
    user_agent = os.getenv("SEC_USER_AGENT", "MarketAlarm/1.4 market-alarm-bot@users.noreply.github.com").strip()
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}


def load_sec_ticker_map(state: dict[str, Any], force: bool) -> dict[str, int]:
    checked = parse_iso(state.get("secTickerMapCheckedAt"))
    cached = state.get("secTickerMap")
    if isinstance(cached, dict) and cached and not force and checked and NOW - checked < timedelta(days=7):
        return {str(k).upper(): int(v) for k, v in cached.items()}
    response = requests.get(
        SEC_TICKERS,
        headers={"User-Agent": sec_headers()["User-Agent"], "Accept-Encoding": "gzip, deflate"},
        timeout=40,
    )
    response.raise_for_status()
    payload = response.json()
    mapping: dict[str, int] = {}
    rows = payload.values() if isinstance(payload, dict) else payload
    for row in rows:
        symbol = clean_text(row.get("ticker")).upper()
        cik = row.get("cik_str")
        if symbol and cik is not None:
            mapping[symbol] = int(cik)
    state["secTickerMap"] = mapping
    state["secTickerMapCheckedAt"] = iso_utc()
    return mapping


SEC_REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
)
SEC_OPERATING_TAGS = ("OperatingIncomeLoss",)
SEC_NET_TAGS = ("NetIncomeLoss", "ProfitLoss")
SEC_EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")


def sec_fact_entries(payload: dict[str, Any], tags: tuple[str, ...], units: tuple[str, ...]) -> list[dict[str, Any]]:
    facts = ((payload.get("facts") or {}).get("us-gaap") or {})
    out: list[dict[str, Any]] = []
    for tag in tags:
        node = facts.get(tag) or {}
        unit_map = node.get("units") or {}
        for unit in units:
            for row in unit_map.get(unit) or []:
                clone = dict(row)
                clone["tag"] = tag
                clone["unit"] = unit
                out.append(clone)
    return out


def sec_choose_current(entries: list[dict[str, Any]], scheduled_date: date) -> dict[str, Any] | None:
    candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for row in entries:
        form = clean_text(row.get("form"))
        if form not in {"10-Q", "10-K", "8-K", "20-F", "6-K"}:
            continue
        filed = parse_korean_date(clean_text(row.get("filed")))
        end = parse_korean_date(clean_text(row.get("end")))
        start = parse_korean_date(clean_text(row.get("start")))
        if not filed or not end:
            continue
        if not (scheduled_date - timedelta(days=3) <= filed <= NOW.astimezone(ET).date() + timedelta(days=1)):
            continue
        if not (scheduled_date - timedelta(days=220) <= end <= scheduled_date + timedelta(days=45)):
            continue
        duration = (end - start).days if start else 999
        quarter_like = 1 if 65 <= duration <= 120 else 0
        annual_like = 1 if 280 <= duration <= 400 else 0
        form_score = 3 if form == "10-Q" else 2 if form in {"8-K", "6-K"} else 1
        score = (quarter_like * 5 + annual_like, form_score, -abs((filed - scheduled_date).days), int(end.strftime("%Y%m%d")))
        candidates.append((score, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def sec_previous_matching(entries: list[dict[str, Any]], current: dict[str, Any]) -> float | None:
    current_end = parse_korean_date(clean_text(current.get("end")))
    current_start = parse_korean_date(clean_text(current.get("start")))
    if not current_end:
        return None
    current_duration = (current_end - current_start).days if current_start else None
    candidates: list[tuple[int, float]] = []
    for row in entries:
        end = parse_korean_date(clean_text(row.get("end")))
        start = parse_korean_date(clean_text(row.get("start")))
        value = safe_float(row.get("val"))
        if not end or value is None:
            continue
        day_gap = abs((current_end - end).days - 365)
        if day_gap > 45:
            continue
        duration = (end - start).days if start else None
        duration_gap = abs((duration or 999) - (current_duration or 999))
        candidates.append((day_gap * 10 + duration_gap, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def extract_sec_company_result(payload: dict[str, Any], scheduled_date: date) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, tags, units in (
        ("revenue", SEC_REVENUE_TAGS, ("USD",)),
        ("operating", SEC_OPERATING_TAGS, ("USD",)),
        ("net", SEC_NET_TAGS, ("USD",)),
        ("eps", SEC_EPS_TAGS, ("USD/shares",)),
    ):
        entries = sec_fact_entries(payload, tags, units)
        current = sec_choose_current(entries, scheduled_date)
        if not current:
            continue
        result[name] = safe_float(current.get("val"))
        result[name + "_previous"] = sec_previous_matching(entries, current)
        result.setdefault("filed", clean_text(current.get("filed")))
        result.setdefault("accn", clean_text(current.get("accn")))
        result.setdefault("period_end", clean_text(current.get("end")))
    return result


def sec_filing_url(cik: int, accn: str) -> str:
    clean_accn = accn.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{clean_accn}/{accn}-index.html" if accn else "https://www.sec.gov/edgar/search/"


def collect_us_results(schedules: list[dict[str, Any]], api_key: str, state: dict[str, Any], force: bool) -> SourceResult:
    """Track recently due U.S. earnings and combine EPS surprise with SEC financial facts."""
    today_et = NOW.astimezone(ET).date()
    candidate_by_symbol: dict[str, dict[str, Any]] = {}
    for item in schedules + load_json(EVENTS_FILE, {}).get("events", []):
        if item.get("market") != "US" or item.get("category") != "earnings" or item.get("status") != "scheduled":
            continue
        symbol = clean_text(item.get("symbol")).upper()
        if not symbol:
            continue
        try:
            d = datetime.fromtimestamp(int(item.get("time", 0)) / 1000, UTC).astimezone(ET).date()
        except Exception:
            continue
        if today_et - timedelta(days=4) <= d <= today_et:
            old = candidate_by_symbol.get(symbol)
            if old is None or int(item.get("importance", 0)) > int(old.get("importance", 0)):
                candidate_by_symbol[symbol] = item
    if not candidate_by_symbol:
        return SourceResult("us_results", [], True, "확인할 최근 미국 실적 없음")

    ticker_map = load_sec_ticker_map(state, force)
    checked = state.setdefault("usResultChecked", {})
    quota = state.setdefault("alphaResultQuota", {})
    quota_date = today_et.isoformat()
    if quota.get("date") != quota_date:
        quota.clear()
        quota.update({"date": quota_date, "calls": 0})
    alpha_remaining = max(0, 20 - int(quota.get("calls", 0)))
    out: list[dict[str, Any]] = []
    checked_count = 0
    ordered = sorted(candidate_by_symbol.values(), key=lambda x: (-int(x.get("importance", 0)), int(x.get("time", 0))))
    for scheduled in ordered[:40]:
        symbol = clean_text(scheduled.get("symbol")).upper()
        checked_at = parse_iso(checked.get(symbol))
        if not force and checked_at and NOW - checked_at < timedelta(hours=4):
            continue
        scheduled_date = datetime.fromtimestamp(int(scheduled.get("time", 0)) / 1000, UTC).astimezone(ET).date()
        eps_actual = eps_estimate = surprise = None
        if api_key and alpha_remaining > 0:
            payload = http_get(ALPHA, params={"function": "EARNINGS", "symbol": symbol, "apikey": api_key}).json()
            quota["calls"] = int(quota.get("calls", 0)) + 1
            alpha_remaining -= 1
            if not payload.get("Information") and not payload.get("Note"):
                for quarter in payload.get("quarterlyEarnings") or []:
                    reported = parse_korean_date(clean_text(quarter.get("reportedDate")))
                    if reported and abs((reported - scheduled_date).days) <= 7:
                        eps_actual = safe_float(quarter.get("reportedEPS"))
                        eps_estimate = safe_float(quarter.get("estimatedEPS"))
                        surprise = safe_float(quarter.get("surprisePercentage"))
                        if surprise is None and eps_estimate not in (None, 0) and eps_actual is not None:
                            surprise = (eps_actual - eps_estimate) / abs(eps_estimate) * 100
                        break

        sec_data: dict[str, Any] = {}
        cik = ticker_map.get(symbol)
        if cik:
            try:
                response = requests.get(SEC_COMPANY_FACTS.format(cik=cik), headers=sec_headers(), timeout=45)
                response.raise_for_status()
                sec_data = extract_sec_company_result(response.json(), scheduled_date)
                time.sleep(0.12)
            except Exception:
                sec_data = {}
        checked[symbol] = iso_utc()
        checked_count += 1
        if eps_actual is None and not any(sec_data.get(k) is not None for k in ("revenue", "operating", "net", "eps")):
            continue
        if eps_actual is None:
            eps_actual = sec_data.get("eps")
        if eps_estimate is None:
            eps_estimate = safe_float(scheduled.get("expected"))
        if surprise is None and eps_estimate not in (None, 0) and eps_actual is not None:
            surprise = (eps_actual - eps_estimate) / abs(eps_estimate) * 100
        operating_yoy = pct_change(sec_data.get("operating"), sec_data.get("operating_previous"))
        revenue_yoy = pct_change(sec_data.get("revenue"), sec_data.get("revenue_previous"))
        rating = result_rating(surprise, operating_yoy if operating_yoy is not None else revenue_yoy)
        parts = [rating_text(rating)]
        if eps_actual is not None:
            eps_text = f"EPS {fmt_num(eps_actual)}"
            if eps_estimate is not None:
                eps_text += f" / 예상 {fmt_num(eps_estimate)}"
            if surprise is not None:
                eps_text += f" ({surprise:+.1f}%)"
            parts.append(eps_text)
        if sec_data.get("revenue") is not None:
            text = f"매출 {format_usd(sec_data['revenue'])}"
            if revenue_yoy is not None:
                text += f" ({revenue_yoy:+.1f}%)"
            parts.append(text)
        if sec_data.get("operating") is not None:
            text = f"영업익 {format_usd(sec_data['operating'])}"
            if operating_yoy is not None:
                text += f" ({operating_yoy:+.1f}%)"
            parts.append(text)
        actual_parts = []
        if eps_actual is not None:
            actual_parts.append(f"EPS {fmt_num(eps_actual)}")
        if sec_data.get("revenue") is not None:
            actual_parts.append(f"매출 {format_usd(sec_data['revenue'])}")
        if sec_data.get("operating") is not None:
            actual_parts.append(f"영업익 {format_usd(sec_data['operating'])}")
        previous_parts = []
        if sec_data.get("revenue_previous") is not None:
            previous_parts.append(f"매출 {format_usd(sec_data['revenue_previous'])}")
        if sec_data.get("operating_previous") is not None:
            previous_parts.append(f"영업익 {format_usd(sec_data['operating_previous'])}")
        when = datetime(scheduled_date.year, scheduled_date.month, scheduled_date.day, 16, 5, tzinfo=ET)
        source_url = sec_filing_url(cik, clean_text(sec_data.get("accn"))) if cik and sec_data else f"https://www.alphavantage.co/query?function=EARNINGS&symbol={symbol}"
        out.append(event(
            event_id=f"us-result-{symbol}-{scheduled_date.isoformat()}",
            title=f"{company_display_name(symbol)} 실적 결과",
            when=when,
            source_key="us_results",
            source=SOURCE_LABELS["us_results"],
            source_url=source_url,
            category="earnings",
            importance=int(scheduled.get("importance", us_importance(symbol))),
            status="released",
            summary=" · ".join(parts),
            symbol=symbol,
            market="US",
            actual=", ".join(actual_parts),
            expected=f"EPS {fmt_num(eps_estimate)}" if eps_estimate is not None else "",
            previous=", ".join(previous_parts),
            rating=rating,
            official=bool(sec_data),
            confidence="official_sec_plus_provider" if sec_data and eps_estimate is not None else "official_sec" if sec_data else "provider",
        ))
    return SourceResult("us_results", out, True, f"최근 미국 실적 {len(out)}개 반영 · 이번 확인 {checked_count}개 · Alpha {quota.get('calls', 0)}/20")

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


def _indicator_item(key: str, label: str, value: float, previous: float | None, unit: str, updated_at: str, source: str, source_url: str) -> dict[str, Any]:
    change = value - previous if previous is not None else None
    change_pct = (change / previous * 100.0) if previous not in (None, 0) else None
    return {
        "key": key, "label": label, "value": value, "previous": previous,
        "change": change, "changePct": change_pct, "unit": unit,
        "updatedAt": updated_at, "source": source, "sourceUrl": source_url,
    }


def fetch_yahoo_indicator(symbol: str, key: str, label: str, unit: str) -> dict[str, Any] | None:
    url = YAHOO_CHART.format(symbol=quote(symbol, safe=""))
    payload = http_get(url, params={"range": "5d", "interval": "1d", "includePrePost": "false"}, timeout=20).json()
    result = (((payload.get("chart") or {}).get("result")) or [None])[0]
    if not result:
        return None
    meta = result.get("meta") or {}
    value = parse_market_cap(meta.get("regularMarketPrice"))
    previous = parse_market_cap(meta.get("chartPreviousClose") or meta.get("previousClose"))
    if value is None:
        closes = (((result.get("indicators") or {}).get("quote")) or [{}])[0].get("close") or []
        valid = [float(v) for v in closes if v is not None]
        if valid:
            value = valid[-1]
            previous = valid[-2] if len(valid) > 1 else previous
    if value is None:
        return None
    timestamp = meta.get("regularMarketTime")
    updated = iso_utc(datetime.fromtimestamp(int(timestamp), UTC)) if timestamp else iso_utc()
    return _indicator_item(key, label, value, previous, unit, updated, "시장 시세 데이터", f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}" )


def fetch_fred_indicator(series: str, key: str, label: str, unit: str) -> dict[str, Any] | None:
    response = http_get(FRED_CSV, params={"id": series}, timeout=25)
    rows = list(csv.DictReader(io.StringIO(response.text)))
    values: list[tuple[str, float]] = []
    for row in rows:
        raw = row.get(series)
        try:
            if raw not in (None, "", "."):
                values.append((str(row.get("DATE") or ""), float(raw)))
        except ValueError:
            continue
    if not values:
        return None
    current_date, value = values[-1]
    previous = values[-2][1] if len(values) > 1 else None
    updated = f"{current_date}T00:00:00Z" if current_date else iso_utc()
    return _indicator_item(key, label, value, previous, unit, updated, "미국 연방준비은행 경제데이터(FRED)", f"https://fred.stlouisfed.org/series/{series}")


def collect_market_indicators(previous: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], bool, str]:
    specs = [
        ("WTI", "WTI 유가", "CL=F", "$/배럴", "DCOILWTICO"),
        ("USDKRW", "원·달러 환율", "KRW=X", "원", "DEXKOUS"),
        ("US10Y", "미국 10년물", "^TNX", "%", "DGS10"),
        ("VIX", "공포지수(VIX)", "^VIX", "pt", "VIXCLS"),
        ("DXY", "달러지수", "DX-Y.NYB", "pt", "DTWEXBGS"),
        ("KOSPI", "코스피", "^KS11", "pt", None),
        ("NASDAQ", "나스닥 종합", "^IXIC", "pt", None),
        ("SOX", "필라델피아 반도체", "^SOX", "pt", None),
        ("BRENT", "브렌트유", "BZ=F", "$/배럴", "DCOILBRENTEU"),
        ("GOLD", "금", "GC=F", "$/oz", None),
        ("COPPER", "구리", "HG=F", "$/lb", None),
        ("BTC", "비트코인", "BTC-USD", "$", None),
    ]
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for key, label, symbol, unit, fred in specs:
        item = None
        try:
            item = fetch_yahoo_indicator(symbol, key, label, unit)
        except Exception as exc:
            errors.append(f"{key}:시세 {exc}")
        if item is None and fred:
            try:
                item = fetch_fred_indicator(fred, key, label, unit)
            except Exception as exc:
                errors.append(f"{key}:FRED {exc}")
        if item:
            out.append(item)
        time.sleep(0.03)
    if not out and previous:
        return previous, False, "새 지표 조회 실패, 이전 값 유지"
    return out, len(out) >= 6, f"핵심 지표 {len(out)}개" + (f" · 일부 실패 {len(errors)}건" if errors else "")


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


def event_company_key(item: dict[str, Any]) -> str:
    symbol = clean_text(item.get("symbol"))
    if symbol:
        return symbol.upper()
    title = clean_text(item.get("title"))
    # Remove the earnings phrase and retain the company portion. Works market-wide,
    # without a named-company list.
    parts = re.split(
        r"\s+(?=(?:20\d{2}년|\d{1,2}분기|1분기|2분기|3분기|4분기|상반기|하반기|연간|경영실적|실적|earnings))",
        title,
        maxsplit=1,
        flags=re.I,
    )
    return re.sub(r"[^0-9A-Za-z가-힣]", "", parts[0]).upper()


def canonical_event_key(item: dict[str, Any]) -> str:
    if item.get("category") == "earnings":
        when_ms = int(item.get("time", 0))
        try:
            event_date = datetime.fromtimestamp(when_ms / 1000, UTC).astimezone(KST if item.get("market") == "KR" else ET).date().isoformat()
        except Exception:
            event_date = str(when_ms)
        company = event_company_key(item)
        status_group = "released" if item.get("status") == "released" else "scheduled"
        return f"earnings|{item.get('market')}|{company}|{event_date}|{status_group}"
    return f"id|{item.get('id', '')}"


def merge_events(new_events: Iterable[dict[str, Any]], old_events: list[dict[str, Any]], failed_sources: set[str]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in new_events:
        if not item.get("id"):
            continue
        key = canonical_event_key(item)
        current = merged.get(key)
        if current is None or event_score(item) >= event_score(current):
            merged[key] = item
    # Keep previously released history, preserve a failed source, and never erase a
    # future Korean earnings date merely because one scrape/API run missed it.
    past_cutoff = NOW_MS - int(timedelta(days=120).total_seconds() * 1000)
    future_cutoff = NOW_MS + int(timedelta(days=400).total_seconds() * 1000)
    for old in old_events:
        if not old.get("id"):
            continue
        key = canonical_event_key(old)
        when = int(old.get("time", 0))
        keep_history = old.get("status") == "released" and past_cutoff <= when <= future_cutoff
        keep_failed_source = old.get("sourceKey") in failed_sources and past_cutoff <= when <= future_cutoff
        keep_future_kr_schedule = (
            old.get("status") == "scheduled"
            and old.get("market") == "KR"
            and old.get("category") == "earnings"
            and NOW_MS - int(timedelta(days=2).total_seconds() * 1000) <= when <= future_cutoff
        )
        if key not in merged and (keep_history or keep_failed_source or keep_future_kr_schedule):
            clone = dict(old)
            if keep_future_kr_schedule:
                clone["confidence"] = "previous_official_schedule"
            merged[key] = clone
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
    old_status = load_json(STATUS_FILE, {})
    state = load_json(STATE_FILE, {})
    dart_key = os.getenv("DART_API_KEY", "").strip()
    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()

    source_functions = [
        ("bls", collect_bls),
        ("bea", collect_bea),
        ("fomc", collect_fomc),
        ("bok", collect_bok),
        ("dart_schedule", lambda: collect_dart_schedules(dart_key, state, force)),
        ("kind", lambda: collect_kind(config, state, force)),
        ("dart", lambda: collect_dart(config, dart_key, state, force)),
        ("nasdaq", lambda: collect_nasdaq_earnings(state, force)),
        ("alpha", lambda: collect_alpha(config, alpha_key, state, force)),
        ("spacex", collect_spacex),
    ]
    results: list[SourceResult] = []
    try:
        cap_result = refresh_kr_market_caps(state, force)
        results.append(cap_result)
        print(f"[krx_marketcap] {cap_result.message}")
    except Exception as exc:
        results.append(SourceResult("krx_marketcap", [], False, str(exc)))
        print(f"[krx_marketcap] ERROR: {exc}", file=sys.stderr)
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

    # Recently due U.S. earnings: EPS surprise plus SEC revenue/operating income.
    try:
        us_result = collect_us_results(all_events, alpha_key, state, force)
        results.append(us_result)
        all_events.extend(us_result.events)
        print(f"[us_results] {len(us_result.events)} updates" + (f" ({us_result.message})" if us_result.message else ""))
    except Exception as exc:
        failed_sources.add("us_results")
        results.append(SourceResult("us_results", [], False, str(exc)))
        print(f"[us_results] ERROR: {exc}", file=sys.stderr)

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

    previous_indicators = old_status.get("indicators", []) if isinstance(old_status, dict) else []
    try:
        indicators, indicators_ok, indicators_message = collect_market_indicators(previous_indicators)
        results.append(SourceResult("market_indicators", [], indicators_ok, indicators_message))
        if not indicators_ok:
            failed_sources.add("market_indicators")
        print(f"[market_indicators] {indicators_message}")
    except Exception as exc:
        indicators = previous_indicators
        failed_sources.add("market_indicators")
        results.append(SourceResult("market_indicators", [], False, str(exc)))
        print(f"[market_indicators] ERROR: {exc}", file=sys.stderr)

    merged = merge_events(all_events, old_events, failed_sources)
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
        "indicators": indicators,
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
