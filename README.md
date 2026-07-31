# 증시알람 v2.0

해외 실적 결과가 Nasdaq·Alpha Vantage 응답에만 의존해 누락되던 문제를 수정한 통합본입니다.

## v2.0 해외 결과 공식 공시 우선 방식
- 해외 실적 달력이 누락돼도 중요 기업을 SEC에서 별도로 확인
- 미국 기업의 8-K Item 2.02, 10-Q, 10-K 실적 공시 감지
- 해외 ADR·외국기업의 6-K, 20-F, 40-F 실적 공시 감지
- SEC 제출 내역은 실시간으로 갱신되는 공식 데이터 사용
- SEC XBRL Company Facts에서 EPS·매출·영업이익·전년 동기 수치 추출
- IFRS 사용 기업의 `ifrs-full` 재무 태그 지원
- Nasdaq·Alpha Vantage 일정이나 결과가 실패해도 SEC 공식 공시만으로 결과 카드 생성
- 세부 수치가 아직 XBRL에 반영되지 않았어도 ‘공식 실적 공시 확인’ 결과를 먼저 표시

## 적용
1. 백엔드 패치의 `collector`와 `.github` 폴더를 GitHub 저장소에 덮어씁니다.
2. `Commit changes`를 누릅니다.
3. `Actions → Update Market Data → Run workflow`를 한 번 실행합니다.
4. 완료 후 앱에서 새로고침합니다.

앱 화면 수정이 아니므로 APK 재설치는 필요 없습니다. 이후에는 예약된 GitHub Actions가 자동으로 갱신합니다.
