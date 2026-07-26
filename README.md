# 증시알람 v1.0

한국·미국의 중요 경제일정, 기업 실적, 중앙은행 일정, SpaceX 발사 일정과 발표 결과를 자동으로 모아 안드로이드 달력과 알림으로 보여주는 독립 앱입니다.

## 이번 버전에서 합쳐진 기능

- GitHub Actions가 매시간 공식·무료 출처를 자동 확인
- APK를 다시 설치하지 않아도 `data/events.json` 갱신
- BLS: CPI, PPI, 고용, JOLTS 등 일정과 실제·이전값
- BEA: GDP, PCE, 개인소득·소비 일정
- Federal Reserve: FOMC 일정과 공식 성명서 공개 확인
- 한국은행: 기준금리 결정 일정
- KIND: 국내 실적·IR 예정 일정
- OpenDART: 국내 공식 실적 공시 결과
- Alpha Vantage: 미국 관심종목 실적 예정·EPS 실제/예상 비교
- Launch Library 2: SpaceX 발사 예정과 결과
- 일정 변경, 하루 전, 1시간 전, 10분 전, 결과 알림
- 오늘·달력·실적·결과·관심종목 화면
- 수집 소스별 정상/실패 상태 표시

일정 날짜를 코드에 고정해 두는 구조가 아닙니다. 수집 실패 시에만 이전에 정상 저장된 데이터를 유지합니다.

## 처음 한 번만 할 일

### 1. 전체 프로젝트 업로드

이 ZIP의 **안쪽 파일 전체**를 `Loshin4/market_alarm` 저장소 최상단에 올립니다. 저장소 첫 화면에 `.github`, `app`, `collector`, `config`, `data`가 바로 보여야 합니다.

### 2. 무료 키 등록

GitHub 저장소에서 `Settings → Secrets and variables → Actions → New repository secret`으로 이동합니다.

- `DART_API_KEY`: OpenDART 무료 인증키. 국내 실적 공시 결과에 사용
- `ALPHA_VANTAGE_API_KEY`: Alpha Vantage 무료 키. 미국 실적 일정과 EPS 예상치 비교에 사용

키가 없어도 BLS·BEA·FOMC·한국은행·KIND·SpaceX는 수집됩니다. 키를 앱에 직접 넣지 않으므로 APK에 노출되지 않습니다.

### 3. 데이터와 APK 만들기

1. `Actions → Update Market Data → Run workflow`
2. 초록색 성공 확인
3. `Actions → Build Android APK → Run workflow`
4. 성공 화면 아래 `market-alarm-apk-v1` 다운로드
5. ZIP 안의 `app-debug.apk`를 휴대폰에 설치

## 이후 자동 업데이트

- GitHub의 `Update Market Data`가 매시간 실행됩니다.
- 앱은 약 1시간마다 GitHub의 최신 JSON을 확인합니다.
- 앱의 `새로고침` 버튼으로 즉시 확인할 수 있습니다.
- GitHub 예약 작업은 서버 상황에 따라 늦게 시작될 수 있으므로 초 단위 실시간은 아닙니다.

## 관심 종목 변경

앱 설정에서는 표시와 알림용 관심종목을 바꿉니다.
수집 자체의 기본 종목을 늘리려면 `config/watchlist.json`을 수정합니다.

## 공식 출처

- BLS: https://www.bls.gov/developers/
- BEA: https://www.bea.gov/news/schedule/icalendar
- Federal Reserve: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- 한국은행: https://www.bok.or.kr/
- KIND: https://kind.krx.co.kr/
- OpenDART: https://opendart.fss.or.kr/
- Alpha Vantage: https://www.alphavantage.co/documentation/
- Launch Library 2: https://thespacedevs.com/llapi
