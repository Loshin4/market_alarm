package com.marketalarm.app;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URLEncoder;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.Month;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class DataRepository {
    private static final String BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics";
    private static final String BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics";
    private static final String FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm";
    private static final String BOK_URL = "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A&pYear=";
    private static final String ALPHA_URL = "https://www.alphavantage.co/query";
    private static final String DART_URL = "https://opendart.fss.or.kr/api/list.json";
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final ZoneId NEW_YORK = ZoneId.of("America/New_York");

    private DataRepository() { }

    public interface Callback {
        void onSuccess(String json, String summary);
        void onError(String message);
    }

    public static void refresh(Context context, Callback callback) {
        new Thread(() -> {
            try {
                JSONArray previous = new JSONArray(Storage.getEvents(context));
                Map<String, JSONObject> merged = new LinkedHashMap<>();
                List<String> sourceStatus = new ArrayList<>();

                collect("BLS", sourceStatus, () -> addAll(merged, fetchIcs(BLS_ICS, "미국 노동통계국(BLS)")));
                collect("BEA", sourceStatus, () -> addAll(merged, fetchIcs(BEA_ICS, "미국 경제분석국(BEA)")));
                collect("FOMC", sourceStatus, () -> addAll(merged, fetchFomc()));
                collect("한국은행", sourceStatus, () -> addAll(merged, fetchBokMeetings()));
                collect("미국 지표결과", sourceStatus, () -> addAll(merged, fetchBlsResults(merged)));

                JSONObject settings = new JSONObject(Storage.getSettings(context));
                String alphaKey = settings.optString("alphaKey", "").trim();
                String dartKey = settings.optString("dartKey", "").trim();
                String watchlist = settings.optString("watchlist", "NVDA,MSFT,GOOGL,AMZN,META");

                if (!blank(alphaKey)) {
                    collect("미국 실적", sourceStatus, () -> {
                        addAll(merged, fetchAlphaCalendar(alphaKey));
                        addAll(merged, fetchAlphaResults(alphaKey, watchlist));
                    });
                } else {
                    sourceStatus.add("미국 실적: 무료 키 미설정");
                }

                if (!blank(dartKey)) {
                    collect("DART", sourceStatus, () -> addAll(merged, fetchDartResults(dartKey)));
                } else {
                    sourceStatus.add("국내 실적: 무료 키 미설정");
                }

                List<JSONObject> sorted = new ArrayList<>(merged.values());
                sorted.sort(Comparator.comparingLong(o -> o.optLong("time", Long.MAX_VALUE)));
                JSONArray result = new JSONArray();
                long cutoffPast = System.currentTimeMillis() - 180L * 24L * 60L * 60L * 1000L;
                long cutoffFuture = System.currentTimeMillis() + 550L * 24L * 60L * 60L * 1000L;
                for (JSONObject event : sorted) {
                    long time = event.optLong("time", 0L);
                    if (time >= cutoffPast && time <= cutoffFuture) result.put(event);
                }

                Storage.saveEvents(context, result.toString());
                AlarmScheduler.scheduleUpcoming(context, result);
                notifyNewResults(context, previous, result);
                String summary = "총 " + result.length() + "개 저장 · " + String.join(" · ", sourceStatus);
                callback.onSuccess(result.toString(), summary);
            } catch (Exception e) {
                callback.onError("일정을 불러오지 못했어요: " + safeMessage(e));
            }
        }, "market-alarm-refresh").start();
    }

    private interface ThrowingRunnable { void run() throws Exception; }

    private static void collect(String name, List<String> statuses, ThrowingRunnable runnable) {
        try {
            runnable.run();
            statuses.add(name + " ✓");
        } catch (Exception e) {
            statuses.add(name + " 실패");
        }
    }

    private static void addAll(Map<String, JSONObject> merged, List<JSONObject> events) {
        for (JSONObject event : events) {
            String id = event.optString("id", "");
            if (!blank(id)) merged.put(id, event);
        }
    }

    private static List<JSONObject> fetchIcs(String url, String source) throws Exception {
        String text = httpGet(url);
        List<String> lines = unfoldIcs(text);
        List<JSONObject> events = new ArrayList<>();
        Map<String, String> current = null;
        for (String line : lines) {
            if ("BEGIN:VEVENT".equals(line)) {
                current = new HashMap<>();
            } else if ("END:VEVENT".equals(line) && current != null) {
                String rawTitle = decodeIcs(current.getOrDefault("SUMMARY", "공식 발표"));
                String dt = current.getOrDefault("DTSTART", "");
                String uid = current.getOrDefault("UID", source + rawTitle + dt);
                long time = parseIcsTime(dt, current.getOrDefault("DTSTART_KEY", ""));
                if (time > 0) {
                    String title = translateTitle(rawTitle);
                    int importance = importanceFor(title);
                    events.add(event(
                            sourceKey(source) + "_" + Integer.toHexString(uid.hashCode()),
                            title, categoryFor(title), source, url, time, importance,
                            "scheduled", null, null, null, "", "", ""
                    ));
                }
                current = null;
            } else if (current != null) {
                int colon = line.indexOf(':');
                if (colon <= 0) continue;
                String key = line.substring(0, colon);
                String value = line.substring(colon + 1).trim();
                String baseKey = key.contains(";") ? key.substring(0, key.indexOf(';')) : key;
                if (baseKey.equals("SUMMARY") || baseKey.equals("DTSTART") || baseKey.equals("UID")) {
                    current.put(baseKey, value);
                    if (baseKey.equals("DTSTART")) current.put("DTSTART_KEY", key);
                }
            }
        }
        return events;
    }

    private static List<String> unfoldIcs(String text) {
        String[] raw = text.replace("\r\n", "\n").replace('\r', '\n').split("\n");
        List<String> out = new ArrayList<>();
        for (String line : raw) {
            if ((line.startsWith(" ") || line.startsWith("\t")) && !out.isEmpty()) {
                int last = out.size() - 1;
                out.set(last, out.get(last) + line.substring(1));
            } else {
                out.add(line.trim());
            }
        }
        return out;
    }

    private static long parseIcsTime(String value, String key) {
        try {
            if (value.matches("\\d{8}")) {
                LocalDate date = LocalDate.parse(value, DateTimeFormatter.BASIC_ISO_DATE);
                return date.atTime(9, 0).atZone(KST).toInstant().toEpochMilli();
            }
            DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss", Locale.US);
            if (value.endsWith("Z")) {
                LocalDateTime ldt = LocalDateTime.parse(value.substring(0, value.length() - 1), formatter);
                return ldt.atZone(ZoneId.of("UTC")).toInstant().toEpochMilli();
            }
            ZoneId zone = key.contains("America/New_York") ? NEW_YORK : KST;
            LocalDateTime ldt = LocalDateTime.parse(value, formatter);
            return ldt.atZone(zone).toInstant().toEpochMilli();
        } catch (Exception e) {
            return 0L;
        }
    }

    private static List<JSONObject> fetchFomc() throws Exception {
        String html = httpGet(FOMC_URL);
        List<String> lines = htmlLines(html);
        List<JSONObject> events = new ArrayList<>();
        int year = LocalDate.now(KST).getYear();
        parseFomcYear(lines, year, events);
        parseFomcYear(lines, year + 1, events);
        return events;
    }

    private static void parseFomcYear(List<String> lines, int year, List<JSONObject> events) throws Exception {
        int start = -1;
        for (int i = 0; i < lines.size(); i++) {
            if (lines.get(i).contains(year + " FOMC Meetings")) { start = i + 1; break; }
        }
        if (start < 0) return;
        Set<String> months = new HashSet<>();
        Collections.addAll(months, "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December", "Jan/Feb", "Apr/May", "Oct/Nov");
        Pattern dayPattern = Pattern.compile("^(\\d{1,2})(?:-(\\d{1,2}))?\\*?.*$");
        for (int i = start; i < lines.size(); i++) {
            String line = lines.get(i);
            if (line.contains("FOMC Meetings") && !line.contains(String.valueOf(year))) break;
            if (!months.contains(line)) continue;
            String dayLine = nextNonEmpty(lines, i + 1);
            Matcher matcher = dayPattern.matcher(dayLine);
            if (!matcher.matches()) continue;
            int endDay = matcher.group(2) == null ? Integer.parseInt(matcher.group(1)) : Integer.parseInt(matcher.group(2));
            int month = monthNumber(line, matcher.group(2) == null ? 1 : 2);
            if (month <= 0) continue;
            ZonedDateTime ny = ZonedDateTime.of(LocalDate.of(year, month, endDay), LocalTime.of(14, 0), NEW_YORK);
            String id = "fomc_" + year + String.format(Locale.US, "%02d%02d", month, endDay);
            events.add(event(id, "미국 FOMC 금리 결정", "fomc", "미국 연방준비제도", FOMC_URL,
                    ny.toInstant().toEpochMilli(), 5, "scheduled", null, null, null, "", "", ""));
        }
    }

    private static int monthNumber(String monthText, int which) {
        String text = monthText;
        if (text.contains("/")) {
            String[] parts = text.split("/");
            text = parts[Math.min(which - 1, parts.length - 1)];
            if (text.equals("Jan")) text = "January";
            if (text.equals("Feb")) text = "February";
            if (text.equals("Apr")) text = "April";
            if (text.equals("May")) text = "May";
            if (text.equals("Oct")) text = "October";
            if (text.equals("Nov")) text = "November";
        }
        try { return Month.valueOf(text.toUpperCase(Locale.US)).getValue(); }
        catch (Exception e) { return 0; }
    }

    private static List<JSONObject> fetchBokMeetings() throws Exception {
        int year = LocalDate.now(KST).getYear();
        List<JSONObject> events = new ArrayList<>();
        for (int y = year; y <= year + 1; y++) {
            String url = BOK_URL + y;
            String html = httpGet(url);
            List<String> lines = htmlLines(html);
            boolean inSection = false;
            Pattern date = Pattern.compile("^(\\d{1,2})월\\s*(\\d{1,2})일.*$");
            Set<String> seen = new HashSet<>();
            for (String line : lines) {
                if (line.equals(y + "년") || line.contains("### " + y + "년")) inSection = true;
                if (!inSection) continue;
                if (line.startsWith("주 :") || line.contains("유용한 정보")) break;
                Matcher matcher = date.matcher(line);
                if (!matcher.matches()) continue;
                int month = Integer.parseInt(matcher.group(1));
                int day = Integer.parseInt(matcher.group(2));
                String key = y + "-" + month + "-" + day;
                if (!seen.add(key)) continue;
                long time = LocalDate.of(y, month, day).atTime(10, 0).atZone(KST).toInstant().toEpochMilli();
                events.add(event("bok_" + y + String.format(Locale.US, "%02d%02d", month, day),
                        "한국은행 금통위 금리 결정", "bok", "한국은행", url, time, 5,
                        "scheduled", null, null, null, "", "", ""));
            }
        }
        return events;
    }


    private static List<JSONObject> fetchBlsResults(Map<String, JSONObject> schedules) throws Exception {
        int year = LocalDate.now(KST).getYear();
        List<JSONObject> results = new ArrayList<>();

        List<SeriesPoint> cpi = fetchBlsSeries("CUUR0000SA0", year - 2, year);
        if (cpi.size() >= 13) {
            SeriesPoint latest = cpi.get(cpi.size() - 1);
            SeriesPoint yearAgo = findPoint(cpi, latest.date.minusYears(1));
            SeriesPoint previousMonth = cpi.get(cpi.size() - 2);
            SeriesPoint previousYearAgo = findPoint(cpi, previousMonth.date.minusYears(1));
            if (yearAgo != null && previousYearAgo != null && yearAgo.value != 0 && previousYearAgo.value != 0) {
                double actual = (latest.value / yearAgo.value - 1.0) * 100.0;
                double previous = (previousMonth.value / previousYearAgo.value - 1.0) * 100.0;
                double delta = actual - previous;
                String emoji = delta <= -0.1 ? "🟢" : delta >= 0.1 ? "🔴" : "⚪";
                String label = delta <= -0.1 ? "물가 둔화" : delta >= 0.1 ? "물가 상승" : "변화 적음";
                String summary = emoji + " 미국 CPI · " + label + "\n실제 " + fmt(actual)
                        + "% | 이전 " + fmt(previous) + "%";
                long time = latestScheduleTime(schedules, "macro_cpi");
                results.add(event("bls_result_cpi_" + latest.key(), "미국 CPI 결과", "macro_cpi",
                        "미국 노동통계국(BLS)", "https://www.bls.gov/cpi/", time, 5, "released",
                        actual, null, previous, "%", emoji, summary));
            }
        }

        List<SeriesPoint> unemployment = fetchBlsSeries("LNS14000000", year - 1, year);
        if (unemployment.size() >= 2) {
            SeriesPoint latest = unemployment.get(unemployment.size() - 1);
            SeriesPoint prev = unemployment.get(unemployment.size() - 2);
            double delta = latest.value - prev.value;
            String emoji = delta <= -0.1 ? "🟢" : delta >= 0.1 ? "🔴" : "⚪";
            String label = delta <= -0.1 ? "개선" : delta >= 0.1 ? "악화" : "변화 적음";
            String summary = emoji + " 미국 실업률 · " + label + "\n실제 " + fmt(latest.value)
                    + "% | 이전 " + fmt(prev.value) + "%";
            long time = latestScheduleTime(schedules, "macro_jobs");
            results.add(event("bls_result_unemp_" + latest.key(), "미국 실업률 결과", "macro_jobs",
                    "미국 노동통계국(BLS)", "https://www.bls.gov/cps/", time, 5, "released",
                    latest.value, null, prev.value, "%", emoji, summary));
        }

        List<SeriesPoint> payroll = fetchBlsSeries("CES0000000001", year - 1, year);
        if (payroll.size() >= 3) {
            SeriesPoint latest = payroll.get(payroll.size() - 1);
            SeriesPoint prev = payroll.get(payroll.size() - 2);
            SeriesPoint before = payroll.get(payroll.size() - 3);
            double actual = latest.value - prev.value;
            double previous = prev.value - before.value;
            double delta = actual - previous;
            String emoji = delta >= 25 ? "🟢" : delta <= -25 ? "🔴" : "⚪";
            String label = delta >= 25 ? "고용 개선" : delta <= -25 ? "고용 둔화" : "변화 적음";
            String summary = emoji + " 미국 비농업 고용 · " + label + "\n실제 " + signed(actual)
                    + "천명 | 이전 " + signed(previous) + "천명";
            long time = latestScheduleTime(schedules, "macro_jobs");
            results.add(event("bls_result_payroll_" + latest.key(), "미국 비농업 고용 결과", "macro_jobs",
                    "미국 노동통계국(BLS)", "https://www.bls.gov/ces/", time, 5, "released",
                    actual, null, previous, "천명", emoji, summary));
        }
        return results;
    }

    private static List<SeriesPoint> fetchBlsSeries(String seriesId, int startYear, int endYear) throws Exception {
        String url = "https://api.bls.gov/publicAPI/v2/timeseries/data/" + seriesId
                + "?startyear=" + startYear + "&endyear=" + endYear;
        JSONObject root = new JSONObject(httpGet(url));
        JSONObject results = root.optJSONObject("Results");
        JSONArray series = results == null ? null : results.optJSONArray("series");
        JSONObject first = series == null ? null : series.optJSONObject(0);
        JSONArray data = first == null ? null : first.optJSONArray("data");
        List<SeriesPoint> points = new ArrayList<>();
        if (data == null) return points;
        for (int i = 0; i < data.length(); i++) {
            JSONObject row = data.optJSONObject(i);
            if (row == null) continue;
            String period = row.optString("period", "");
            String y = row.optString("year", "");
            if (!period.matches("M\\d{2}") || !y.matches("\\d{4}")) continue;
            int month = Integer.parseInt(period.substring(1));
            if (month < 1 || month > 12) continue;
            Double value = numberOrNull(row.optString("value", ""));
            if (value == null) continue;
            points.add(new SeriesPoint(LocalDate.of(Integer.parseInt(y), month, 1), value));
        }
        points.sort(Comparator.comparing(point -> point.date));
        return points;
    }

    private static SeriesPoint findPoint(List<SeriesPoint> points, LocalDate date) {
        for (SeriesPoint point : points) {
            if (point.date.getYear() == date.getYear() && point.date.getMonthValue() == date.getMonthValue()) return point;
        }
        return null;
    }

    private static long latestScheduleTime(Map<String, JSONObject> schedules, String category) {
        long now = System.currentTimeMillis();
        long best = 0L;
        for (JSONObject event : schedules.values()) {
            if (!category.equals(event.optString("category", ""))) continue;
            if (!event.optString("source", "").contains("BLS")) continue;
            long time = event.optLong("time", 0L);
            if (time <= now + 24L * 60L * 60L * 1000L && time > best) best = time;
        }
        return best > 0 ? best : now;
    }

    private static final class SeriesPoint {
        final LocalDate date;
        final double value;
        SeriesPoint(LocalDate date, double value) { this.date = date; this.value = value; }
        String key() { return date.getYear() + String.format(Locale.US, "%02d", date.getMonthValue()); }
    }

    private static List<JSONObject> fetchAlphaCalendar(String apiKey) throws Exception {
        String url = ALPHA_URL + "?function=EARNINGS_CALENDAR&horizon=3month&apikey=" + enc(apiKey);
        String csv = httpGet(url);
        List<List<String>> rows = parseCsv(csv);
        if (rows.size() < 2) return Collections.emptyList();
        List<String> header = rows.get(0);
        int symbolIdx = header.indexOf("symbol");
        int nameIdx = header.indexOf("name");
        int reportIdx = header.indexOf("reportDate");
        int estimateIdx = header.indexOf("estimate");
        List<JSONObject> events = new ArrayList<>();
        for (int i = 1; i < rows.size(); i++) {
            List<String> row = rows.get(i);
            if (reportIdx < 0 || row.size() <= reportIdx) continue;
            String reportDate = row.get(reportIdx);
            if (!reportDate.matches("\\d{4}-\\d{2}-\\d{2}")) continue;
            String symbol = valueAt(row, symbolIdx);
            String name = valueAt(row, nameIdx);
            Double estimate = numberOrNull(valueAt(row, estimateIdx));
            long time = LocalDate.parse(reportDate).atTime(5, 20).atZone(KST).toInstant().toEpochMilli();
            String title = (blank(symbol) ? name : symbol) + " 실적 발표";
            JSONObject event = event("alpha_cal_" + symbol + "_" + reportDate, title, "earnings_us",
                    "Alpha Vantage", "https://www.alphavantage.co/", time,
                    majorSymbol(symbol) ? 5 : 3, "scheduled", null, estimate, null,
                    " EPS", "", "");
            event.put("symbol", symbol);
            events.add(event);
        }
        return events;
    }

    private static List<JSONObject> fetchAlphaResults(String apiKey, String watchlist) throws Exception {
        List<JSONObject> events = new ArrayList<>();
        String[] symbols = watchlist.toUpperCase(Locale.US).split("[,\\s]+");
        int calls = 0;
        for (String symbol : symbols) {
            symbol = symbol.trim();
            if (blank(symbol) || calls >= 5) continue;
            calls++;
            String url = ALPHA_URL + "?function=EARNINGS&symbol=" + enc(symbol) + "&apikey=" + enc(apiKey);
            JSONObject data = new JSONObject(httpGet(url));
            JSONArray quarterly = data.optJSONArray("quarterlyEarnings");
            if (quarterly == null || quarterly.length() == 0) continue;
            JSONObject latest = quarterly.optJSONObject(0);
            if (latest == null) continue;
            String reportedDate = latest.optString("reportedDate", "");
            if (!reportedDate.matches("\\d{4}-\\d{2}-\\d{2}")) continue;
            Double actual = numberOrNull(latest.optString("reportedEPS", ""));
            Double expected = numberOrNull(latest.optString("estimatedEPS", ""));
            Double surprise = numberOrNull(latest.optString("surprisePercentage", ""));
            String emoji = ratingEmoji(surprise);
            String label = ratingLabel(surprise);
            String summary = emoji + " " + symbol + " 실적 · " + label + "\n실제 " + fmt(actual)
                    + " EPS | 예상 " + fmt(expected) + " EPS"
                    + (surprise == null ? "" : " | " + signed(surprise) + "%");
            long time = LocalDate.parse(reportedDate).atTime(5, 20).atZone(KST).toInstant().toEpochMilli();
            JSONObject event = event("alpha_result_" + symbol + "_" + reportedDate,
                    symbol + " 실적 결과", "earnings_us", "Alpha Vantage",
                    "https://www.alphavantage.co/", time, majorSymbol(symbol) ? 5 : 4,
                    "released", actual, expected, null, " EPS", emoji, summary);
            event.put("symbol", symbol);
            events.add(event);
        }
        return events;
    }

    private static List<JSONObject> fetchDartResults(String apiKey) throws Exception {
        LocalDate end = LocalDate.now(KST);
        LocalDate start = end.minusDays(10);
        String url = DART_URL + "?crtfc_key=" + enc(apiKey)
                + "&bgn_de=" + start.format(DateTimeFormatter.BASIC_ISO_DATE)
                + "&end_de=" + end.format(DateTimeFormatter.BASIC_ISO_DATE)
                + "&page_count=100";
        JSONObject data = new JSONObject(httpGet(url));
        JSONArray list = data.optJSONArray("list");
        if (list == null) return Collections.emptyList();
        Pattern important = Pattern.compile("잠정.*실적|영업.*실적|매출액|손익구조|분기보고서|반기보고서|사업보고서");
        List<JSONObject> events = new ArrayList<>();
        for (int i = 0; i < list.length(); i++) {
            JSONObject row = list.optJSONObject(i);
            if (row == null) continue;
            String report = row.optString("report_nm", "");
            if (!important.matcher(report).find()) continue;
            String corp = row.optString("corp_name", "국내기업");
            String date = row.optString("rcept_dt", "");
            String receipt = row.optString("rcept_no", "");
            if (!date.matches("\\d{8}")) continue;
            LocalDate d = LocalDate.parse(date, DateTimeFormatter.BASIC_ISO_DATE);
            long time = d.atTime(18, 0).atZone(KST).toInstant().toEpochMilli();
            String sourceUrl = blank(receipt) ? "https://dart.fss.or.kr/" :
                    "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + receipt;
            String summary = "⚪ " + corp + " 공시 결과\n" + report;
            events.add(event("dart_" + receipt, corp + " · " + report, "earnings_kr",
                    "금융감독원 OpenDART", sourceUrl, time, 4, "released",
                    null, null, null, "", "⚪", summary));
        }
        return events;
    }

    private static JSONObject event(String id, String title, String category, String source,
                                    String sourceUrl, long time, int importance, String status,
                                    Double actual, Double expected, Double previous, String unit,
                                    String rating, String summary) throws Exception {
        JSONObject event = new JSONObject();
        event.put("id", id);
        event.put("title", title);
        event.put("category", category);
        event.put("source", source);
        event.put("sourceUrl", sourceUrl);
        event.put("time", time);
        event.put("importance", importance);
        event.put("status", status);
        event.put("actual", actual == null ? JSONObject.NULL : actual);
        event.put("expected", expected == null ? JSONObject.NULL : expected);
        event.put("previous", previous == null ? JSONObject.NULL : previous);
        event.put("unit", unit == null ? "" : unit);
        event.put("rating", rating == null ? "" : rating);
        event.put("summary", summary == null ? "" : summary);
        return event;
    }

    private static void notifyNewResults(Context context, JSONArray oldEvents, JSONArray newEvents) {
        Set<String> oldIds = new HashSet<>();
        for (int i = 0; i < oldEvents.length(); i++) {
            JSONObject obj = oldEvents.optJSONObject(i);
            if (obj != null) oldIds.add(obj.optString("id", ""));
        }
        int sent = 0;
        for (int i = 0; i < newEvents.length() && sent < 5; i++) {
            JSONObject obj = newEvents.optJSONObject(i);
            if (obj == null || !"released".equals(obj.optString("status"))) continue;
            String id = obj.optString("id", "");
            if (blank(id) || oldIds.contains(id)) continue;
            String summary = obj.optString("summary", obj.optString("title", "새 결과"));
            NotificationHelper.notify(context, id.hashCode(), "📊 새 발표 결과", summary);
            sent++;
        }
    }

    private static String httpGet(String address) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(20000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("User-Agent", "MarketAlarm-Android/0.3 personal-use");
        connection.setRequestProperty("Accept", "*/*");
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code);
        BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8));
        StringBuilder builder = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) builder.append(line).append('\n');
        reader.close();
        connection.disconnect();
        return builder.toString();
    }

    private static List<String> htmlLines(String html) {
        String text = html
                .replaceAll("(?is)<script.*?</script>", " ")
                .replaceAll("(?is)<style.*?</style>", " ")
                .replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("(?i)</(div|p|li|tr|td|th|h1|h2|h3|h4|h5|section)>", "\n")
                .replaceAll("(?s)<[^>]+>", " ");
        text = htmlDecode(text);
        String[] raw = text.replace("\r", "\n").split("\n");
        List<String> lines = new ArrayList<>();
        for (String line : raw) {
            String clean = line.replace('\u00a0', ' ').replaceAll("\\s+", " ").trim();
            if (!blank(clean)) lines.add(clean);
        }
        return lines;
    }

    private static String nextNonEmpty(List<String> lines, int start) {
        for (int i = start; i < lines.size(); i++) if (!blank(lines.get(i))) return lines.get(i);
        return "";
    }

    private static String htmlDecode(String value) {
        return value.replace("&nbsp;", " ").replace("&#160;", " ")
                .replace("&amp;", "&").replace("&quot;", "\"")
                .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">");
    }

    private static String decodeIcs(String value) {
        return value.replace("\\,", ",").replace("\\;", ";")
                .replace("\\n", " ").replace("\\N", " ").replace("\\\\", "\\");
    }

    private static String translateTitle(String title) {
        String t = title.trim();
        if (t.contains("Consumer Price Index")) return "미국 소비자물가지수(CPI)";
        if (t.contains("Producer Price Index")) return "미국 생산자물가지수(PPI)";
        if (t.contains("Employment Situation")) return "미국 고용보고서";
        if (t.contains("Job Openings and Labor Turnover")) return "미국 구인·이직(JOLTS)";
        if (t.contains("Employment Cost Index")) return "미국 고용비용지수(ECI)";
        if (t.contains("Gross Domestic Product")) return "미국 GDP · " + t.replace("Gross Domestic Product", "").replace("\\,", ",").trim();
        if (t.contains("Personal Income and Outlays")) return "미국 PCE·개인소득 · " + t.replace("Personal Income and Outlays", "").trim();
        if (t.contains("International Trade in Goods and Services")) return "미국 무역수지 · " + t.replace("U.S. International Trade in Goods and Services", "").trim();
        if (t.contains("Corporate Profits")) return "미국 기업이익 · " + t;
        return t;
    }

    private static int importanceFor(String title) {
        String t = title.toLowerCase(Locale.US);
        if (t.contains("cpi") || t.contains("고용보고서") || t.contains("pce") || t.contains("gdp") || t.contains("fomc")) return 5;
        if (t.contains("ppi") || t.contains("jolts") || t.contains("고용비용") || t.contains("기업이익")) return 4;
        if (t.contains("무역") || t.contains("실업") || t.contains("productivity")) return 3;
        return 2;
    }

    private static String categoryFor(String title) {
        String t = title.toLowerCase(Locale.US);
        if (t.contains("cpi")) return "macro_cpi";
        if (t.contains("ppi")) return "macro_ppi";
        if (t.contains("고용") || t.contains("jolts")) return "macro_jobs";
        if (t.contains("pce")) return "macro_pce";
        if (t.contains("gdp")) return "macro_gdp";
        return "macro_other";
    }

    private static String sourceKey(String source) {
        if (source.contains("BLS")) return "bls";
        if (source.contains("BEA")) return "bea";
        return "src";
    }

    private static boolean majorSymbol(String symbol) {
        return symbol.equals("NVDA") || symbol.equals("MSFT") || symbol.equals("AAPL") || symbol.equals("AMZN")
                || symbol.equals("GOOGL") || symbol.equals("GOOG") || symbol.equals("META")
                || symbol.equals("TSLA") || symbol.equals("AVGO");
    }

    private static String ratingEmoji(Double surprise) {
        if (surprise == null) return "⚪";
        if (surprise >= 8) return "🟢🟢";
        if (surprise >= 2) return "🟢";
        if (surprise <= -8) return "🔴🔴";
        if (surprise <= -2) return "🔴";
        return "⚪";
    }

    private static String ratingLabel(Double surprise) {
        if (surprise == null) return "중립";
        if (surprise >= 8) return "매우 좋음";
        if (surprise >= 2) return "좋음";
        if (surprise <= -8) return "매우 나쁨";
        if (surprise <= -2) return "나쁨";
        return "중립";
    }

    private static Double numberOrNull(String value) {
        try {
            if (blank(value) || value.equalsIgnoreCase("None")) return null;
            return Double.parseDouble(value.replace(",", ""));
        } catch (Exception e) { return null; }
    }

    private static String fmt(Double value) {
        if (value == null) return "-";
        if (Math.rint(value) == value) return String.format(Locale.US, "%.0f", value);
        return String.format(Locale.US, "%.2f", value).replaceAll("0+$", "").replaceAll("\\.$", "");
    }

    private static String signed(Double value) {
        if (value == null) return "-";
        return (value > 0 ? "+" : "") + fmt(value);
    }

    private static String enc(String value) throws Exception {
        return URLEncoder.encode(value, StandardCharsets.UTF_8.toString());
    }

    private static boolean blank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static String safeMessage(Exception e) {
        String message = e.getMessage();
        return blank(message) ? e.getClass().getSimpleName() : message;
    }

    private static List<List<String>> parseCsv(String text) {
        List<List<String>> rows = new ArrayList<>();
        List<String> row = new ArrayList<>();
        StringBuilder cell = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '"') {
                if (quoted && i + 1 < text.length() && text.charAt(i + 1) == '"') {
                    cell.append('"'); i++;
                } else quoted = !quoted;
            } else if (c == ',' && !quoted) {
                row.add(cell.toString().trim()); cell.setLength(0);
            } else if ((c == '\n' || c == '\r') && !quoted) {
                if (c == '\r' && i + 1 < text.length() && text.charAt(i + 1) == '\n') i++;
                row.add(cell.toString().trim()); cell.setLength(0);
                if (!(row.size() == 1 && blank(row.get(0)))) rows.add(row);
                row = new ArrayList<>();
            } else cell.append(c);
        }
        if (cell.length() > 0 || !row.isEmpty()) {
            row.add(cell.toString().trim()); rows.add(row);
        }
        return rows;
    }

    private static String valueAt(List<String> row, int index) {
        return index >= 0 && index < row.size() ? row.get(index) : "";
    }
}
