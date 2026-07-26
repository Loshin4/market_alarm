package com.marketalarm.app;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.Month;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class DataRepository {
    private static final String PREFS = "market_alarm";
    private static final String KEY_EVENTS = "events";
    private static final String KEY_SETTINGS = "settings";
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private static final String BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics";
    private static final String BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics";
    private static final String FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm";
    private static final String BOK_URL = "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A";
    private static final String BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/";

    private DataRepository() { }

    public interface RefreshCallback {
        void onSuccess(String eventsJson, String message);
        void onError(String eventsJson, String message);
    }

    public static String getCachedEvents(Context context) {
        return prefs(context).getString(KEY_EVENTS, "[]");
    }

    public static String getSettings(Context context) {
        return prefs(context).getString(KEY_SETTINGS, "{\"watchlist\":\"NVDA,MSFT,GOOGL,AMZN,META\",\"krWatchlist\":\"삼성전자,SK하이닉스\"}");
    }

    public static void saveSettings(Context context, String json) {
        prefs(context).edit().putString(KEY_SETTINGS, json == null ? "{}" : json).apply();
    }

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static void refreshAll(Context context, RefreshCallback callback) {
        EXECUTOR.execute(() -> {
            List<JSONObject> events = new ArrayList<>();
            List<String> errors = new ArrayList<>();
            int[] counts = new int[5];

            try { List<JSONObject> x = parseIcs(fetch(BLS_ICS), "미국 노동통계국 BLS", BLS_ICS, "macro"); events.addAll(x); counts[0] = x.size(); }
            catch (Exception e) { errors.add("BLS"); }
            try { List<JSONObject> x = parseIcs(fetch(BEA_ICS), "미국 경제분석국 BEA", BEA_ICS, "macro"); events.addAll(x); counts[1] = x.size(); }
            catch (Exception e) { errors.add("BEA"); }
            try { List<JSONObject> x = fetchFomc(); events.addAll(x); counts[2] = x.size(); }
            catch (Exception e) { errors.add("FOMC"); addFomcFallback(events); }
            try { List<JSONObject> x = fetchBok(); events.addAll(x); counts[3] = x.size(); }
            catch (Exception e) { errors.add("한국은행"); addBokFallback(events); }

            JSONObject settings = safeObject(getSettings(context));
            String alphaKey = settings.optString("alphaKey", "").trim();
            String watchlist = settings.optString("watchlist", "NVDA,MSFT,GOOGL,AMZN,META");
            if (!alphaKey.isEmpty()) {
                try { List<JSONObject> x = fetchAlphaEarnings(alphaKey, watchlist); events.addAll(x); counts[4] = x.size(); }
                catch (Exception e) { errors.add("미국 실적"); }
            }

            try { attachBlsResults(events); }
            catch (Exception ignored) { }

            deduplicateAndSort(events);
            String json = toJson(events).toString();
            if (!events.isEmpty()) {
                prefs(context).edit().putString(KEY_EVENTS, json).apply();
                NotificationHelper.scheduleEventReminders(context, events);
                String message = "일정 " + events.size() + "개 저장 · BLS " + counts[0] + " · BEA " + counts[1] + " · FOMC " + counts[2] + " · 한국은행 " + counts[3];
                if (!errors.isEmpty()) message += " · 일부 실패: " + String.join(", ", errors);
                callback.onSuccess(json, message);
            } else {
                String cached = getCachedEvents(context);
                callback.onError(cached, "일정을 불러오지 못했어. 인터넷 연결을 확인해줘.");
            }
        });
    }

    public static void refreshInBackground(Context context) {
        refreshAll(context, new RefreshCallback() {
            @Override public void onSuccess(String eventsJson, String message) { }
            @Override public void onError(String eventsJson, String message) { }
        });
    }

    private static JSONObject safeObject(String json) {
        try { return new JSONObject(json); } catch (Exception e) { return new JSONObject(); }
    }

    private static String fetch(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(25000);
        c.setRequestProperty("User-Agent", "Mozilla/5.0 (Android) MarketAlarm/0.4");
        c.setRequestProperty("Accept-Language", "ko-KR,ko;q=0.9,en-US;q=0.8");
        c.setInstanceFollowRedirects(true);
        int code = c.getResponseCode();
        if (code < 200 || code >= 300) throw new Exception("HTTP " + code);
        return readAll(c.getInputStream());
    }

    private static String postJson(String url, JSONObject body) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(25000);
        c.setRequestMethod("POST");
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
        c.setRequestProperty("User-Agent", "MarketAlarm/0.4");
        try (BufferedWriter w = new BufferedWriter(new OutputStreamWriter(c.getOutputStream(), StandardCharsets.UTF_8))) { w.write(body.toString()); }
        int code = c.getResponseCode();
        if (code < 200 || code >= 300) throw new Exception("HTTP " + code);
        return readAll(c.getInputStream());
    }

    private static String readAll(InputStream in) throws Exception {
        StringBuilder b = new StringBuilder();
        try (BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            char[] buf = new char[8192]; int n;
            while ((n = r.read(buf)) >= 0) b.append(buf, 0, n);
        }
        return b.toString();
    }

    private static List<JSONObject> parseIcs(String raw, String source, String sourceUrl, String category) throws Exception {
        String text = raw.replace("\r\n ", "").replace("\n ", "");
        List<JSONObject> out = new ArrayList<>();
        String[] blocks = text.split("BEGIN:VEVENT");
        for (int i = 1; i < blocks.length; i++) {
            String block = blocks[i];
            String summary = field(block, "SUMMARY");
            String dtLine = lineStarting(block, "DTSTART");
            if (summary.isEmpty() || dtLine.isEmpty()) continue;
            long time = parseIcsDate(dtLine);
            if (time <= 0) continue;
            summary = cleanIcs(summary);
            int importance = importance(summary);
            out.add(event(source + "-" + time + "-" + summary.hashCode(), translate(summary), time, source, sourceUrl, category, importance, "scheduled", ""));
        }
        return out;
    }

    private static String field(String block, String name) {
        for (String line : block.split("\r?\n")) {
            if (line.startsWith(name + ":")) return line.substring(name.length() + 1);
            if (line.startsWith(name + ";")) {
                int p = line.indexOf(':'); if (p >= 0) return line.substring(p + 1);
            }
        }
        return "";
    }

    private static String lineStarting(String block, String name) {
        for (String line : block.split("\r?\n")) if (line.startsWith(name)) return line;
        return "";
    }

    private static String cleanIcs(String s) {
        return s.replace("\\,", ",").replace("\\n", " ").replace("\\;", ";").trim();
    }

    private static long parseIcsDate(String line) {
        try {
            String value = line.substring(line.indexOf(':') + 1).trim();
            if (value.matches("\\d{8}T\\d{6}Z")) {
                return ZonedDateTime.parse(value, DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssX")).toInstant().toEpochMilli();
            }
            if (value.matches("\\d{8}T\\d{4}Z")) {
                return ZonedDateTime.parse(value, DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmX")).toInstant().toEpochMilli();
            }
            ZoneId zone = line.contains("America/New_York") ? ZoneId.of("America/New_York") : ZoneId.of("Asia/Seoul");
            if (value.matches("\\d{8}T\\d{6}")) return LocalDateTime.parse(value, DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss")).atZone(zone).toInstant().toEpochMilli();
            if (value.matches("\\d{8}T\\d{4}")) return LocalDateTime.parse(value, DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmm")).atZone(zone).toInstant().toEpochMilli();
            if (value.matches("\\d{8}")) return LocalDate.parse(value, DateTimeFormatter.BASIC_ISO_DATE).atTime(9, 0).atZone(zone).toInstant().toEpochMilli();
        } catch (Exception ignored) { }
        return 0;
    }

    private static List<JSONObject> fetchFomc() throws Exception {
        String html = fetch(FED_URL);
        String text = html.replaceAll("(?is)<script.*?</script>", " ").replaceAll("(?is)<style.*?</style>", " ").replaceAll("(?s)<[^>]+>", " ").replace("&nbsp;", " ");
        text = text.replaceAll("\\s+", " ");
        List<JSONObject> out = new ArrayList<>();
        for (int year = LocalDate.now().getYear() - 1; year <= LocalDate.now().getYear() + 1; year++) {
            int start = text.indexOf(year + " FOMC Meetings");
            if (start < 0) continue;
            int end = text.indexOf((year - 1) + " FOMC Meetings", start + 10);
            if (end < 0) end = text.indexOf((year + 1) + " FOMC Meetings", start + 10);
            if (end < 0) end = Math.min(text.length(), start + 4000);
            String section = text.substring(start, Math.min(end, text.length()));
            Pattern p = Pattern.compile("(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(\\d{1,2})(?:-(\\d{1,2}))?\\*?");
            Matcher m = p.matcher(section);
            while (m.find()) {
                Month month = Month.valueOf(m.group(1).toUpperCase(Locale.US));
                int day = m.group(3) == null ? Integer.parseInt(m.group(2)) : Integer.parseInt(m.group(3));
                LocalDate date = LocalDate.of(year, month, day);
                long time = date.atTime(14, 0).atZone(ZoneId.of("America/New_York")).toInstant().toEpochMilli();
                out.add(event("fomc-" + year + "-" + month + "-" + day, "미국 FOMC 금리결정", time, "미국 연방준비제도", FED_URL, "macro", 5, "scheduled", ""));
            }
        }
        if (out.isEmpty()) throw new Exception("parse");
        return out;
    }

    private static void addFomcFallback(List<JSONObject> out) {
        int[][] dates2026 = {{1,28},{3,18},{4,29},{6,17},{7,29},{9,16},{10,28},{12,9}};
        int[][] dates2027 = {{1,27},{3,17},{4,28},{6,9},{7,28},{9,15},{10,27},{12,8}};
        addFixedDates(out, 2026, dates2026, "미국 FOMC 금리결정", "미국 연방준비제도", FED_URL, ZoneId.of("America/New_York"), 14, 0, 5);
        addFixedDates(out, 2027, dates2027, "미국 FOMC 금리결정", "미국 연방준비제도", FED_URL, ZoneId.of("America/New_York"), 14, 0, 5);
    }

    private static List<JSONObject> fetchBok() throws Exception {
        String html = fetch(BOK_URL);
        String text = html.replaceAll("(?is)<script.*?</script>", " ").replaceAll("(?is)<style.*?</style>", " ").replaceAll("(?s)<[^>]+>", " ").replace("&nbsp;", " ");
        text = text.replaceAll("\\s+", " ");
        List<JSONObject> out = new ArrayList<>();
        Pattern yearP = Pattern.compile("(20\\d{2})년");
        Matcher ym = yearP.matcher(text);
        int year = LocalDate.now().getYear();
        int start = text.indexOf(year + "년");
        if (start < 0) start = 0;
        String section = text.substring(start, Math.min(text.length(), start + 15000));
        Matcher m = Pattern.compile("(\\d{1,2})월\\s*(\\d{1,2})일").matcher(section);
        Set<String> seen = new HashSet<>();
        while (m.find()) {
            int month = Integer.parseInt(m.group(1)), day = Integer.parseInt(m.group(2));
            String k = month + "-" + day;
            if (!seen.add(k)) continue;
            try {
                long time = LocalDate.of(year, month, day).atTime(10, 0).atZone(ZoneId.of("Asia/Seoul")).toInstant().toEpochMilli();
                out.add(event("bok-" + year + "-" + k, "한국은행 기준금리 결정", time, "한국은행", BOK_URL, "macro", 5, "scheduled", ""));
            } catch (Exception ignored) { }
        }
        if (out.size() < 4) throw new Exception("parse");
        return out;
    }

    private static void addBokFallback(List<JSONObject> out) {
        int[][] dates2026 = {{1,15},{2,26},{4,10},{5,28},{7,16},{8,27},{10,22},{11,26}};
        addFixedDates(out, 2026, dates2026, "한국은행 기준금리 결정", "한국은행", BOK_URL, ZoneId.of("Asia/Seoul"), 10, 0, 5);
    }

    private static void addFixedDates(List<JSONObject> out, int year, int[][] md, String title, String source, String url, ZoneId zone, int hour, int minute, int importance) {
        for (int[] d : md) {
            long time = LocalDate.of(year, d[0], d[1]).atTime(hour, minute).atZone(zone).toInstant().toEpochMilli();
            out.add(event(source.hashCode() + "-" + year + "-" + d[0] + "-" + d[1], title, time, source, url, "macro", importance, "scheduled", ""));
        }
    }

    private static List<JSONObject> fetchAlphaEarnings(String key, String watchlist) throws Exception {
        List<JSONObject> out = new ArrayList<>();
        String[] symbols = watchlist.split("[,\\s]+");
        int limit = Math.min(symbols.length, 8);
        for (int i = 0; i < limit; i++) {
            String symbol = symbols[i].trim().toUpperCase(Locale.US);
            if (symbol.isEmpty()) continue;
            String url = "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&symbol=" + URLEncoder.encode(symbol, "UTF-8") + "&horizon=3month&apikey=" + URLEncoder.encode(key, "UTF-8");
            String csv = fetch(url);
            String[] lines = csv.split("\\r?\\n");
            for (int r = 1; r < lines.length; r++) {
                List<String> cols = parseCsvLine(lines[r]);
                if (cols.size() < 4 || cols.get(0).isEmpty() || cols.get(2).isEmpty()) continue;
                LocalDate date = LocalDate.parse(cols.get(2));
                String reportTime = cols.size() > 3 ? cols.get(3) : "";
                int hour = "AfterMarket".equalsIgnoreCase(reportTime) ? 16 : 8;
                ZoneId ny = ZoneId.of("America/New_York");
                long time = date.atTime(hour, 0).atZone(ny).toInstant().toEpochMilli();
                String estimate = cols.size() > 6 ? cols.get(6) : "";
                String summary = estimate.isEmpty() ? "" : "예상 EPS " + estimate;
                out.add(event("earn-" + symbol + "-" + date, symbol + " 실적 발표", time, "Alpha Vantage 무료", url, "earnings", 4, "scheduled", summary));
            }

            try {
                String earningsUrl = "https://www.alphavantage.co/query?function=EARNINGS&symbol=" + URLEncoder.encode(symbol, "UTF-8") + "&apikey=" + URLEncoder.encode(key, "UTF-8");
                JSONObject j = new JSONObject(fetch(earningsUrl));
                JSONArray q = j.optJSONArray("quarterlyEarnings");
                if (q != null && q.length() > 0) {
                    JSONObject latest = q.getJSONObject(0);
                    LocalDate date = LocalDate.parse(latest.optString("reportedDate"));
                    double actual = parseDouble(latest.optString("reportedEPS"));
                    double estimate = parseDouble(latest.optString("estimatedEPS"));
                    double surprise = estimate == 0 ? 0 : (actual - estimate) / Math.abs(estimate) * 100.0;
                    String mood = surprise >= 5 ? "🟢🟢 매우 좋음" : surprise > 0 ? "🟢 좋음" : surprise <= -5 ? "🔴🔴 매우 나쁨" : surprise < 0 ? "🔴 나쁨" : "⚪ 중립";
                    String summary = mood + "\nEPS " + fmt(actual) + " / 예상 " + fmt(estimate) + " · " + (surprise >= 0 ? "+" : "") + String.format(Locale.US, "%.1f%%", surprise);
                    long time = date.atTime(16, 5).atZone(ZoneId.of("America/New_York")).toInstant().toEpochMilli();
                    out.add(event("earn-result-" + symbol + "-" + date, symbol + " 실적 결과", time, "Alpha Vantage 무료", earningsUrl, "earnings", 4, "released", summary));
                }
            } catch (Exception ignored) { }
        }
        return out;
    }

    private static List<String> parseCsvLine(String line) {
        List<String> out = new ArrayList<>(); StringBuilder b = new StringBuilder(); boolean quote = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"') { if (quote && i + 1 < line.length() && line.charAt(i + 1) == '"') { b.append('"'); i++; } else quote = !quote; }
            else if (c == ',' && !quote) { out.add(b.toString().trim()); b.setLength(0); }
            else b.append(c);
        }
        out.add(b.toString().trim()); return out;
    }

    private static void attachBlsResults(List<JSONObject> events) throws Exception {
        int year = LocalDate.now().getYear();
        JSONArray ids = new JSONArray();
        ids.put("CUUR0000SA0");       // CPI all items
        ids.put("WPUFD4");            // Final demand PPI
        ids.put("LNS14000000");       // unemployment rate
        ids.put("CES0000000001");     // total nonfarm payroll
        JSONObject body = new JSONObject();
        body.put("seriesid", ids); body.put("startyear", String.valueOf(year - 1)); body.put("endyear", String.valueOf(year));
        JSONObject root = new JSONObject(postJson(BLS_API, body));
        JSONArray series = root.getJSONObject("Results").getJSONArray("series");
        Map<String, String> resultMap = new HashMap<>();
        for (int i = 0; i < series.length(); i++) {
            JSONObject s = series.getJSONObject(i);
            String id = s.optString("seriesID"); JSONArray data = s.optJSONArray("data");
            if (data == null || data.length() < 2) continue;
            JSONObject latest = data.getJSONObject(0), prev = data.getJSONObject(1);
            double a = parseDouble(latest.optString("value")), b = parseDouble(prev.optString("value"));
            String label; String unit; boolean higherGood;
            switch (id) {
                case "CUUR0000SA0": label = "CPI"; unit = ""; higherGood = false; break;
                case "WPUFD4": label = "PPI"; unit = ""; higherGood = false; break;
                case "LNS14000000": label = "실업률"; unit = "%"; higherGood = false; break;
                default: label = "비농업 고용"; unit = "K"; a /= 1000.0; b /= 1000.0; higherGood = true;
            }
            double diff = a - b;
            String mood = Math.abs(diff) < 0.0001 ? "⚪" : ((diff > 0) == higherGood ? "🟢" : "🔴");
            resultMap.put(label, mood + " " + label + " " + fmt(a) + unit + " · 이전 " + fmt(b) + unit);
        }
        for (JSONObject e : events) {
            String title = e.optString("title"); String key = null;
            if (title.contains("소비자물가") || title.toLowerCase(Locale.US).contains("consumer price")) key = "CPI";
            else if (title.contains("생산자물가") || title.toLowerCase(Locale.US).contains("producer price")) key = "PPI";
            else if (title.contains("고용보고서") || title.toLowerCase(Locale.US).contains("employment situation")) key = "비농업 고용";
            if (key != null && resultMap.containsKey(key) && e.optLong("time") < System.currentTimeMillis()) {
                e.put("status", "released"); e.put("summary", resultMap.get(key));
            }
        }
    }

    private static JSONObject event(String id, String title, long time, String source, String sourceUrl, String category, int importance, String status, String summary) {
        JSONObject j = new JSONObject();
        try {
            j.put("id", id); j.put("title", title); j.put("time", time); j.put("source", source); j.put("sourceUrl", sourceUrl);
            j.put("category", category); j.put("importance", importance); j.put("status", status); j.put("summary", summary);
        } catch (JSONException ignored) { }
        return j;
    }

    private static int importance(String s) {
        String x = s.toLowerCase(Locale.US);
        if (x.contains("consumer price") || x.contains("employment situation") || x.contains("gross domestic product") || x.contains("personal income and outlays")) return 5;
        if (x.contains("producer price") || x.contains("job openings") || x.contains("employment cost") || x.contains("retail") || x.contains("trade")) return 4;
        return 3;
    }

    private static String translate(String s) {
        String x = s;
        x = x.replace("Consumer Price Index", "미국 소비자물가 CPI");
        x = x.replace("Producer Price Index", "미국 생산자물가 PPI");
        x = x.replace("The Employment Situation", "미국 고용보고서");
        x = x.replace("Job Openings and Labor Turnover Survey", "미국 JOLTS 구인·이직");
        x = x.replace("Gross Domestic Product", "미국 GDP");
        x = x.replace("Personal Income and Outlays", "미국 개인소득·소비/PCE");
        x = x.replace("U.S. International Trade in Goods and Services", "미국 무역수지");
        return x;
    }

    private static void deduplicateAndSort(List<JSONObject> list) {
        Map<String, JSONObject> map = new HashMap<>();
        long min = LocalDate.now().minusMonths(18).atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant().toEpochMilli();
        long max = LocalDate.now().plusMonths(18).atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant().toEpochMilli();
        for (JSONObject j : list) {
            long t = j.optLong("time"); if (t < min || t > max) continue;
            String k = j.optString("title").toLowerCase(Locale.US).replaceAll("\\s+", " ") + "|" + (t / 3600000L);
            JSONObject old = map.get(k);
            if (old == null || j.optInt("importance") > old.optInt("importance")) map.put(k, j);
        }
        list.clear(); list.addAll(map.values());
        Collections.sort(list, Comparator.comparingLong(o -> o.optLong("time")));
    }

    private static JSONArray toJson(List<JSONObject> list) {
        JSONArray a = new JSONArray(); for (JSONObject j : list) a.put(j); return a;
    }

    private static double parseDouble(String s) {
        try { return Double.parseDouble(s.replace(",", "")); } catch (Exception e) { return 0; }
    }

    private static String fmt(double v) {
        if (Math.abs(v - Math.rint(v)) < 0.00001) return String.format(Locale.US, "%.0f", v);
        return String.format(Locale.US, "%.2f", v).replaceAll("0+$", "").replaceAll("\\.$", "");
    }
}
