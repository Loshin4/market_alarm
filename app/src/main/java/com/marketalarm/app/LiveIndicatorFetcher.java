package com.marketalarm.app;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

public final class LiveIndicatorFetcher {
    private static final class Spec {
        final String key;
        final String label;
        final String symbol;
        final String unit;

        Spec(String key, String label, String symbol, String unit) {
            this.key = key;
            this.label = label;
            this.symbol = symbol;
            this.unit = unit;
        }
    }

    private static final Spec[] SPECS = new Spec[] {
            new Spec("WTI", "WTI 유가", "CL=F", "$/배럴"),
            new Spec("USDKRW", "원·달러 환율", "KRW=X", "원"),
            new Spec("US10Y", "미국 10년물", "^TNX", "%"),
            new Spec("VIX", "공포지수(VIX)", "^VIX", "pt"),
            new Spec("DXY", "달러지수", "DX-Y.NYB", "pt"),
            new Spec("KOSPI", "코스피", "^KS11", "pt"),
            new Spec("NASDAQ", "나스닥 종합", "^IXIC", "pt"),
            new Spec("SOX", "필라델피아 반도체", "^SOX", "pt"),
            new Spec("BRENT", "브렌트유", "BZ=F", "$/배럴"),
            new Spec("GOLD", "금", "GC=F", "$/oz"),
            new Spec("COPPER", "구리", "HG=F", "$/lb"),
            new Spec("BTC", "비트코인", "BTC-USD", "$"),
    };

    private LiveIndicatorFetcher() { }

    public static JSONArray fetchAll(JSONArray fallback) {
        Map<String, JSONObject> previous = new HashMap<>();
        if (fallback != null) {
            for (int i = 0; i < fallback.length(); i++) {
                JSONObject item = fallback.optJSONObject(i);
                if (item != null) previous.put(item.optString("key"), item);
            }
        }

        ExecutorService pool = Executors.newFixedThreadPool(4);
        List<Future<JSONObject>> futures = new ArrayList<>();
        for (Spec spec : SPECS) futures.add(pool.submit(() -> fetchOne(spec)));

        JSONArray output = new JSONArray();
        try {
            for (int i = 0; i < SPECS.length; i++) {
                JSONObject item = null;
                try { item = futures.get(i).get(25, TimeUnit.SECONDS); }
                catch (Exception ignored) { }
                if (item == null) item = previous.get(SPECS[i].key);
                if (item != null) output.put(item);
            }
        } finally {
            pool.shutdownNow();
        }
        return output;
    }

    private static JSONObject fetchOne(Spec spec) throws Exception {
        String encoded = URLEncoder.encode(spec.symbol, StandardCharsets.UTF_8.name());
        String url = "https://query1.finance.yahoo.com/v8/finance/chart/" + encoded
                + "?range=1d&interval=1m&includePrePost=true&events=div%2Csplits";
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(15000);
        connection.setRequestProperty("User-Agent", "Mozilla/5.0 MarketAlarmAndroid/1.7");
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Cache-Control", "no-cache");
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code);
        JSONObject root = new JSONObject(readAll(connection.getInputStream()));
        JSONObject chart = root.optJSONObject("chart");
        JSONArray results = chart == null ? null : chart.optJSONArray("result");
        if (results == null || results.length() == 0) return null;
        JSONObject result = results.optJSONObject(0);
        if (result == null) return null;
        JSONObject meta = result.optJSONObject("meta");
        JSONArray timestamps = result.optJSONArray("timestamp");
        JSONObject indicators = result.optJSONObject("indicators");
        JSONArray quoteArray = indicators == null ? null : indicators.optJSONArray("quote");
        JSONObject quote = quoteArray == null ? null : quoteArray.optJSONObject(0);
        JSONArray closes = quote == null ? null : quote.optJSONArray("close");

        double value = Double.NaN;
        long timestamp = 0L;
        if (timestamps != null && closes != null) {
            int count = Math.min(timestamps.length(), closes.length());
            for (int i = count - 1; i >= 0; i--) {
                if (closes.isNull(i)) continue;
                double candidate = closes.optDouble(i, Double.NaN);
                if (Double.isFinite(candidate)) {
                    value = candidate;
                    timestamp = timestamps.optLong(i, 0L);
                    break;
                }
            }
        }
        if (!Double.isFinite(value) && meta != null) value = meta.optDouble("regularMarketPrice", Double.NaN);
        if (!Double.isFinite(value)) return null;
        double previous = meta == null ? Double.NaN : meta.optDouble("chartPreviousClose", Double.NaN);
        if (!Double.isFinite(previous) && meta != null) previous = meta.optDouble("previousClose", Double.NaN);
        if (timestamp <= 0 && meta != null) timestamp = meta.optLong("regularMarketTime", 0L);

        JSONObject item = new JSONObject();
        item.put("key", spec.key);
        item.put("label", spec.label);
        item.put("value", value);
        if (Double.isFinite(previous)) {
            double change = value - previous;
            item.put("previous", previous);
            item.put("change", change);
            item.put("changePct", previous == 0 ? JSONObject.NULL : change / previous * 100.0);
        } else {
            item.put("previous", JSONObject.NULL);
            item.put("change", JSONObject.NULL);
            item.put("changePct", JSONObject.NULL);
        }
        item.put("unit", spec.unit);
        item.put("updatedAt", timestamp > 0 ? Instant.ofEpochSecond(timestamp).toString() : Instant.now().toString());
        item.put("source", "시장 장중 시세 · 앱 직접 확인");
        item.put("sourceUrl", "https://finance.yahoo.com/quote/" + encoded);
        return item;
    }

    private static String readAll(InputStream inputStream) throws Exception {
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {
            char[] buffer = new char[8192];
            int read;
            while ((read = reader.read(buffer)) >= 0) builder.append(buffer, 0, read);
        }
        return builder.toString();
    }
}
