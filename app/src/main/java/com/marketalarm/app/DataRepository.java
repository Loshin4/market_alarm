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
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public final class DataRepository {
    private static final String PREFS = "market_alarm";
    private static final String KEY_EVENTS = "events";
    private static final String KEY_EVENTS_HASH = "events_hash";
    private static final String KEY_STATUS = "status";
    private static final String KEY_SETTINGS = "settings";
    private static final String KEY_LAST_SYNC = "last_sync";
    private static final String KEY_LAST_STATUS_SYNC = "last_status_sync";
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
                "{\"notifyNew\":true,\"notifyDay\":true,\"notifyHour\":true,\"notifyTen\":true,"
                        + "\"notifyResults\":true,\"notifyChanges\":true,"
                        + "\"dataUrl\":\"" + DEFAULT_DATA_URL + "\"}");
    }

    public static long getLastSync(Context context) {
        return prefs(context).getLong(KEY_LAST_SYNC, 0L);
    }

    public static void saveSettings(Context context, String json) {
        JSONObject current = safeObject(getSettings(context));
        JSONObject incoming = safeObject(json);
        String oldUrl = current.optString("dataUrl", DEFAULT_DATA_URL);
        String[] keys = {"dataUrl", "notifyNew", "notifyDay", "notifyHour", "notifyTen", "notifyResults", "notifyChanges"};
        for (String key : keys) {
            if (incoming.has(key)) {
                try { current.put(key, incoming.get(key)); } catch (Exception ignored) { }
            }
        }
        SharedPreferences.Editor editor = prefs(context).edit().putString(KEY_SETTINGS, current.toString());
        if (!oldUrl.equals(current.optString("dataUrl", DEFAULT_DATA_URL))) {
            editor.remove(KEY_EVENTS_HASH).putLong(KEY_LAST_SYNC, 0L);
        }
        editor.apply();
    }

    public static boolean shouldRefresh(Context context) {
        long last = prefs(context).getLong(KEY_LAST_SYNC, 0L);
        return System.currentTimeMillis() - last > 25L * 60L * 1000L;
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
                JSONObject status = null;
                try { status = new JSONObject(fetch(addCacheBuster(statusUrl))); }
                catch (Exception ignored) { }

                JSONArray oldEvents = safeArray(cachedEvents);
                String remoteHash = status == null ? "" : status.optString("eventsHash", "");
                String localHash = prefs(context).getString(KEY_EVENTS_HASH, "");
                if (!remoteHash.isEmpty() && remoteHash.equals(localHash) && oldEvents.length() > 0) {
                    if (status == null) status = safeObject(cachedStatus);
                    prefs(context).edit()
                            .putString(KEY_STATUS, status.toString())
                            .putLong(KEY_LAST_SYNC, System.currentTimeMillis())
                            .apply();
                    NotificationHelper.scheduleEventReminders(context, toList(oldEvents), settings);
                    String updated = status.optString("updatedAt", "");
                    String message = "새 일정·결과 없음 · 저장된 " + oldEvents.length() + "개 유지";
                    if (!updated.isEmpty()) message += " · " + compactTime(updated);
                    callback.onSuccess(cachedEvents, status.toString(), message);
                    return;
                }

                String rootText = fetch(addCacheBuster(dataUrl));
                JSONObject root = new JSONObject(rootText);
                JSONArray newEvents = root.optJSONArray("events");
                if (newEvents == null) throw new IllegalStateException("events 배열 없음");
                if (status == null) {
                    status = new JSONObject();
                    status.put("updatedAt", root.optString("updatedAt", ""));
                    status.put("ok", true);
                    status.put("message", "일정 데이터는 정상 수신됨");
                }

                notifyMeaningfulChanges(context, oldEvents, newEvents, settings);
                String eventsHash = !remoteHash.isEmpty() ? remoteHash : root.optString("eventsHash", "");
                SharedPreferences.Editor editor = prefs(context).edit()
                        .putString(KEY_EVENTS, newEvents.toString())
                        .putString(KEY_STATUS, status.toString())
                        .putLong(KEY_LAST_SYNC, System.currentTimeMillis());
                if (!eventsHash.isEmpty()) editor.putString(KEY_EVENTS_HASH, eventsHash);
                editor.apply();
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

    public static void refreshStatusOnly(Context context, RefreshCallback callback) {
        EXECUTOR.execute(() -> {
            String cachedEvents = getCachedEvents(context);
            String cachedStatus = getCachedStatus(context);
            try {
                JSONObject settings = safeObject(getSettings(context));
                String dataUrl = settings.optString("dataUrl", DEFAULT_DATA_URL).trim();
                if (!dataUrl.startsWith("https://")) dataUrl = DEFAULT_DATA_URL;
                String statusUrl = deriveStatusUrl(dataUrl);
                JSONObject status = safeObject(cachedStatus);
                long now = System.currentTimeMillis();
                long lastStatusSync = prefs(context).getLong(KEY_LAST_STATUS_SYNC, 0L);
                if (now - lastStatusSync > 10L * 60L * 1000L) {
                    try {
                        status = new JSONObject(fetch(addMinuteCacheBuster(statusUrl)));
                        prefs(context).edit().putLong(KEY_LAST_STATUS_SYNC, now).apply();
                    } catch (Exception ignored) { }
                }
                JSONArray liveIndicators = LiveIndicatorFetcher.fetchAll(status.optJSONArray("indicators"));
                if (liveIndicators.length() > 0) {
                    status.put("indicators", liveIndicators);
                    status.put("indicatorUpdatedAt", java.time.Instant.now().toString());
                }
                prefs(context).edit().putString(KEY_STATUS, status.toString()).apply();
                String updated = status.optString("indicatorUpdatedAt", status.optString("updatedAt", ""));
                String message = "시장 지표 업데이트";
                if (!updated.isEmpty()) message += " · " + compactTime(updated);
                callback.onSuccess(cachedEvents, status.toString(), message);
            } catch (Exception e) {
                callback.onError(cachedEvents, cachedStatus, "지표 업데이트 실패 · " + readableError(e));
            }
        });
    }

    public static boolean refreshBlocking(Context context) {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicBoolean success = new AtomicBoolean(false);
        refreshAll(context, new RefreshCallback() {
            @Override public void onSuccess(String eventsJson, String statusJson, String message) {
                success.set(true);
                latch.countDown();
            }
            @Override public void onError(String eventsJson, String statusJson, String message) {
                latch.countDown();
            }
        });
        try {
            return latch.await(3, TimeUnit.MINUTES) && success.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
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
        long bucket = System.currentTimeMillis() / (5L * 60L * 1000L);
        return url + (url.contains("?") ? "&" : "?") + "v=" + bucket;
    }

    private static String addMinuteCacheBuster(String url) {
        long bucket = System.currentTimeMillis() / (60L * 1000L);
        return url + (url.contains("?") ? "&" : "?") + "v=" + bucket;
    }

    private static String fetch(String url) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(25000);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent", "MarketAlarmAndroid/1.2");
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
        List<JSONObject> pending = new ArrayList<>();
        for (int i = 0; i < newEvents.length() && pending.size() < 20; i++) {
            JSONObject current = newEvents.optJSONObject(i);
            if (current == null || current.optInt("importance", 0) < 4) continue;
            JSONObject old = oldMap.get(current.optString("id"));
            if (settings.optBoolean("notifyNew", true) && oldEvents.length() > 0 && old == null
                    && !"released".equals(current.optString("status"))) {
                long eventTime = current.optLong("time");
                if (eventTime > now + 30L * 60L * 1000L
                        && eventTime < now + 120L * 24L * 60L * 60L * 1000L) {
                    addPending(pending, "new", current, 0L);
                    continue;
                }
            }
            if (notifyResults && "released".equals(current.optString("status"))) {
                boolean newlyReleased = old == null || !"released".equals(old.optString("status"))
                        || !current.optString("summary").equals(old.optString("summary"));
                long eventTime = current.optLong("time");
                if (newlyReleased && eventTime > now - 36L * 60L * 60L * 1000L) {
                    addPending(pending, "result", current, 0L);
                    continue;
                }
            }
            if (notifyChanges && old != null && !"released".equals(current.optString("status"))) {
                long oldTime = old.optLong("time");
                long newTime = current.optLong("time");
                if (newTime > now && Math.abs(oldTime - newTime) >= 5L * 60L * 1000L) {
                    addPending(pending, "change", current, oldTime);
                }
            }
        }
        if (pending.size() > 3) {
            NotificationHelper.notifyBatchSummary(context, pending);
            return;
        }
        for (JSONObject notice : pending) {
            JSONObject event = notice.optJSONObject("event");
            if (event == null) continue;
            String kind = notice.optString("kind");
            if ("new".equals(kind)) NotificationHelper.notifyNewSchedule(context, event);
            else if ("result".equals(kind)) NotificationHelper.notifyResult(context, event);
            else if ("change".equals(kind)) NotificationHelper.notifyScheduleChange(context, event, notice.optLong("oldTime"));
        }
    }

    private static void addPending(List<JSONObject> pending, String kind, JSONObject event, long oldTime) {
        try {
            JSONObject notice = new JSONObject();
            notice.put("kind", kind);
            notice.put("event", event);
            notice.put("oldTime", oldTime);
            pending.add(notice);
        } catch (Exception ignored) { }
    }

    public static boolean matchesWatchlist(JSONObject event, JSONObject settings) {
        return false;
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
