package com.marketalarm.app;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class DataRepository {
    private static final String PREFS = "market_alarm";
    private static final String KEY_EVENTS = "events";
    private static final String KEY_STATUS = "status";
    private static final String KEY_SETTINGS = "settings";
    private static final String KEY_LAST_SYNC = "last_sync";
    private static final String DEFAULT_DATA_URL = "https://raw.githubusercontent.com/Loshin4/market_alarm/main/data/events.json";
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private DataRepository() { }

    public interface RefreshCallback {
        void onSuccess(String eventsJson, String statusJson, String message);
        void onError(String eventsJson, String statusJson, String message);
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static String getCachedEvents(Context context) {
        return prefs(context).getString(KEY_EVENTS, "[]");
    }

    public static String getCachedStatus(Context context) {
        return prefs(context).getString(KEY_STATUS,
                "{\"updatedAt\":null,\"ok\":false,\"message\":\"데이터 업데이트 대기 중\",\"counts\":{},\"sources\":{}}");
    }

    public static String getSettings(Context context) {
        return prefs(context).getString(KEY_SETTINGS,
                "{\"watchlist\":\"NVDA,MSFT,AAPL,AMZN,META,GOOGL,TSLA\","
                        + "\"krWatchlist\":\"삼성전자,SK하이닉스\","
                        + "\"notifyDay\":true,\"notifyHour\":true,\"notifyTen\":true,"
                        + "\"notifyResults\":true,\"notifyChanges\":true,"
                        + "\"dataUrl\":\"" + DEFAULT_DATA_URL + "\"}");
    }

    public static void saveSettings(Context context, String json) {
        JSONObject current = safeObject(getSettings(context));
        JSONObject incoming = safeObject(json);
        String[] keys = {"watchlist", "krWatchlist", "dataUrl", "notifyDay", "notifyHour", "notifyTen", "notifyResults", "notifyChanges"};
        for (String key : keys) {
            if (incoming.has(key)) {
                try { current.put(key, incoming.get(key)); } catch (Exception ignored) { }
            }
        }
        prefs(context).edit().putString(KEY_SETTINGS, current.toString()).apply();
    }

    public static boolean shouldRefresh(Context context) {
        long last = prefs(context).getLong(KEY_LAST_SYNC, 0L);
        return System.currentTimeMillis() - last > 45L * 60L * 1000L;
    }

    public static void refreshAll(Context context, RefreshCallback callback) {
        EXECUTOR.execute(() -> {
            String cachedEvents = getCachedEvents(context);
            String cachedStatus = getCachedStatus(context);
            try {
                JSONObject settings = safeObject(getSettings(context));
                String dataUrl = settings.optString("dataUrl", DEFAULT_DATA_URL).trim();
                if (!dataUrl.startsWith("https://")) dataUrl = DEFAULT_DATA_URL;
                String statusUrl = deriveStatusUrl(dataUrl);
                String rootText = fetch(addCacheBuster(dataUrl));
                JSONObject root = new JSONObject(rootText);
                JSONArray newEvents = root.optJSONArray("events");
                if (newEvents == null) throw new IllegalStateException("events 배열 없음");
                JSONObject status;
                try { status = new JSONObject(fetch(addCacheBuster(statusUrl))); }
                catch (Exception ignored) {
                    status = new JSONObject();
                    status.put("updatedAt", root.optString("updatedAt", ""));
                    status.put("ok", true);
                    status.put("message", "일정 데이터는 정상 수신됨");
                }

                JSONArray oldEvents = safeArray(cachedEvents);
                notifyMeaningfulChanges(context, oldEvents, newEvents, settings);
                prefs(context).edit()
                        .putString(KEY_EVENTS, newEvents.toString())
                        .putString(KEY_STATUS, status.toString())
                        .putLong(KEY_LAST_SYNC, System.currentTimeMillis())
                        .apply();
                NotificationHelper.scheduleEventReminders(context, toList(newEvents), settings);

                String updated = status.optString("updatedAt", root.optString("updatedAt", ""));
                String message = "일정 " + newEvents.length() + "개 업데이트";
                if (!updated.isEmpty()) message += " · " + compactTime(updated);
                callback.onSuccess(newEvents.toString(), status.toString(), message);
            } catch (Exception e) {
                callback.onError(cachedEvents, cachedStatus, "업데이트 실패 · " + readableError(e));
            }
        });
    }

    public static void refreshInBackground(Context context) {
        refreshAll(context, new RefreshCallback() {
            @Override public void onSuccess(String eventsJson, String statusJson, String message) { }
            @Override public void onError(String eventsJson, String statusJson, String message) { }
        });
    }

    private static String deriveStatusUrl(String dataUrl) {
        int slash = dataUrl.lastIndexOf('/');
        return slash >= 0 ? dataUrl.substring(0, slash + 1) + "status.json" : dataUrl;
    }

    private static String addCacheBuster(String url) {
        long bucket = System.currentTimeMillis() / (10L * 60L * 1000L);
        return url + (url.contains("?") ? "&" : "?") + "v=" + bucket;
    }

    private static String fetch(String url) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(25000);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent", "MarketAlarmAndroid/1.0");
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Cache-Control", "no-cache");
        int code = connection.getResponseCode();
        if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code);
        return readAll(connection.getInputStream());
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

    private static void notifyMeaningfulChanges(Context context, JSONArray oldEvents, JSONArray newEvents, JSONObject settings) {
        Map<String, JSONObject> oldMap = new HashMap<>();
        for (int i = 0; i < oldEvents.length(); i++) {
            JSONObject item = oldEvents.optJSONObject(i);
            if (item != null) oldMap.put(item.optString("id"), item);
        }
        boolean notifyResults = settings.optBoolean("notifyResults", true);
        boolean notifyChanges = settings.optBoolean("notifyChanges", true);
        long now = System.currentTimeMillis();
        int sent = 0;
        for (int i = 0; i < newEvents.length() && sent < 8; i++) {
            JSONObject current = newEvents.optJSONObject(i);
            if (current == null) continue;
            JSONObject old = oldMap.get(current.optString("id"));
            boolean watched = matchesWatchlist(current, settings);
            boolean important = current.optInt("importance", 0) >= 4 || watched;
            if (!important) continue;
            if (notifyResults && "released".equals(current.optString("status"))) {
                boolean newlyReleased = old == null || !"released".equals(old.optString("status"))
                        || !current.optString("summary").equals(old.optString("summary"));
                long eventTime = current.optLong("time");
                if (newlyReleased && eventTime > now - 7L * 24L * 60L * 60L * 1000L) {
                    NotificationHelper.notifyResult(context, current);
                    sent++;
                    continue;
                }
            }
            if (notifyChanges && old != null && !"released".equals(current.optString("status"))) {
                long oldTime = old.optLong("time");
                long newTime = current.optLong("time");
                if (newTime > now && Math.abs(oldTime - newTime) >= 5L * 60L * 1000L) {
                    NotificationHelper.notifyScheduleChange(context, current, oldTime);
                    sent++;
                }
            }
        }
    }

    public static boolean matchesWatchlist(JSONObject event, JSONObject settings) {
        Set<String> tokens = new HashSet<>();
        addTokens(tokens, settings.optString("watchlist", ""));
        addTokens(tokens, settings.optString("krWatchlist", ""));
        String symbol = normalize(event.optString("symbol", ""));
        String title = normalize(event.optString("title", ""));
        if (!symbol.isEmpty() && tokens.contains(symbol)) return true;
        for (String token : tokens) if (token.length() >= 2 && title.contains(token)) return true;
        return false;
    }

    private static void addTokens(Set<String> out, String raw) {
        for (String value : raw.split("[,\\n]+")) {
            String token = normalize(value);
            if (!token.isEmpty()) out.add(token);
        }
    }

    private static String normalize(String value) {
        return value == null ? "" : value.replaceAll("\\s+", "").toUpperCase(Locale.US);
    }

    private static List<JSONObject> toList(JSONArray array) {
        List<JSONObject> list = new ArrayList<>();
        for (int i = 0; i < array.length(); i++) {
            JSONObject item = array.optJSONObject(i);
            if (item != null) list.add(item);
        }
        return list;
    }

    private static JSONObject safeObject(String json) {
        try { return new JSONObject(json); } catch (Exception ignored) { return new JSONObject(); }
    }

    private static JSONArray safeArray(String json) {
        try { return new JSONArray(json); } catch (Exception ignored) { return new JSONArray(); }
    }

    private static String compactTime(String iso) {
        try {
            String text = iso.replace("T", " ").replace("Z", " UTC");
            return text.length() > 16 ? text.substring(0, 16) : text;
        } catch (Exception ignored) { return iso; }
    }

    private static String readableError(Exception e) {
        String message = e.getMessage();
        if (message == null || message.trim().isEmpty()) return e.getClass().getSimpleName();
        return message.length() > 100 ? message.substring(0, 100) : message;
    }
}
