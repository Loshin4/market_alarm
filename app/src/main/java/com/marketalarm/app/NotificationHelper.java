package com.marketalarm.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

public final class NotificationHelper {
    public static final String CHANNEL_SCHEDULE = "market_schedule";
    public static final String CHANNEL_RESULTS = "market_results";
    private static final String PREFS = "market_alarm_notifications";
    private static final String KEY_REQUESTS = "requests";

    private NotificationHelper() { }

    public static void ensureChannels(Context context) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        NotificationChannel schedule = new NotificationChannel(CHANNEL_SCHEDULE, "증시 일정", NotificationManager.IMPORTANCE_HIGH);
        schedule.setDescription("중요 일정 사전 알림과 일정 변경");
        NotificationChannel results = new NotificationChannel(CHANNEL_RESULTS, "발표 결과", NotificationManager.IMPORTANCE_HIGH);
        results.setDescription("경제지표와 기업 실적 발표 결과");
        manager.createNotificationChannel(schedule);
        manager.createNotificationChannel(results);
    }

    public static void scheduleEventReminders(Context context, List<JSONObject> events, JSONObject settings) {
        ensureChannels(context);
        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        cancelPrevious(context, alarmManager);
        List<Integer> requestIds = new ArrayList<>();
        long now = System.currentTimeMillis();
        long max = now + 400L * 24L * 60L * 60L * 1000L;
        int scheduled = 0;
        for (JSONObject event : events) {
            if (scheduled >= 240) break;
            if (event.optInt("importance", 0) < 4 && !DataRepository.matchesWatchlist(event, settings)) continue;
            if ("released".equals(event.optString("status"))) continue;
            long eventTime = event.optLong("time");
            if (eventTime <= now || eventTime > max) continue;
            List<Long> offsets = new ArrayList<>();
            List<Integer> labels = new ArrayList<>();
            if (settings.optBoolean("notifyDay", true)) { offsets.add(24L * 60L * 60L * 1000L); labels.add(1440); }
            if (settings.optBoolean("notifyHour", true)) { offsets.add(60L * 60L * 1000L); labels.add(60); }
            if (settings.optBoolean("notifyTen", true)) { offsets.add(10L * 60L * 1000L); labels.add(10); }
            for (int i = 0; i < offsets.size(); i++) {
                long triggerAt = eventTime - offsets.get(i);
                if (triggerAt <= now) continue;
                int requestId = Math.abs((event.optString("id") + "-" + labels.get(i)).hashCode());
                Intent intent = new Intent(context, ReminderReceiver.class);
                intent.putExtra("title", event.optString("title"));
                intent.putExtra("minutes", labels.get(i));
                PendingIntent pendingIntent = PendingIntent.getBroadcast(context, requestId, intent,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent);
                requestIds.add(requestId);
                scheduled++;
            }
        }
        saveRequestIds(context, requestIds);
    }

    private static void cancelPrevious(Context context, AlarmManager alarmManager) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String raw = prefs.getString(KEY_REQUESTS, "");
        for (String piece : raw.split(",")) {
            if (piece.trim().isEmpty()) continue;
            try {
                int requestId = Integer.parseInt(piece.trim());
                PendingIntent pendingIntent = PendingIntent.getBroadcast(context, requestId,
                        new Intent(context, ReminderReceiver.class), PendingIntent.FLAG_NO_CREATE | PendingIntent.FLAG_IMMUTABLE);
                if (pendingIntent != null) alarmManager.cancel(pendingIntent);
            } catch (Exception ignored) { }
        }
    }

    private static void saveRequestIds(Context context, List<Integer> ids) {
        StringBuilder builder = new StringBuilder();
        for (Integer id : ids) {
            if (builder.length() > 0) builder.append(',');
            builder.append(id);
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_REQUESTS, builder.toString()).apply();
    }

    public static void notifyResult(Context context, JSONObject event) {
        ensureChannels(context);
        String title = compactRating(event) + " " + event.optString("title", "발표 결과");
        String body = event.optString("summary", "공식 결과가 업데이트됐어.");
        post(context, CHANNEL_RESULTS, Math.abs(("result-" + event.optString("id") + body).hashCode()), title, body);
    }

    public static void notifyScheduleChange(Context context, JSONObject event, long oldTime) {
        ensureChannels(context);
        String body = "기존 " + formatKst(oldTime) + " → 변경 " + formatKst(event.optLong("time"));
        post(context, CHANNEL_SCHEDULE, Math.abs(("change-" + event.optString("id") + event.optLong("time")).hashCode()),
                "⚠️ 일정 변경 · " + event.optString("title"), body);
    }

    public static void postReminder(Context context, String title, int minutes) {
        ensureChannels(context);
        String prefix = minutes >= 1440 ? "내일" : minutes + "분 전";
        String body = minutes >= 1440 ? title + " 일정이 내일 있어." : title + " 발표가 " + minutes + "분 남았어.";
        post(context, CHANNEL_SCHEDULE, Math.abs((title + minutes).hashCode()), "⏰ " + prefix, body);
    }

    private static void post(Context context, String channel, int id, String title, String body) {
        Intent open = new Intent(context, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, channel)
                : new Notification.Builder(context);
        Notification notification = builder
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setPriority(Notification.PRIORITY_HIGH)
                .build();
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        manager.notify(id, notification);
    }

    private static String compactRating(JSONObject event) {
        int rating = event.optInt("rating", 0);
        if (rating >= 2) return "🟢🟢";
        if (rating == 1) return "🟢";
        if (rating <= -2) return "🔴🔴";
        if (rating == -1) return "🔴";
        return "⚪";
    }

    private static String formatKst(long millis) {
        SimpleDateFormat format = new SimpleDateFormat("M/d HH:mm", Locale.KOREA);
        format.setTimeZone(TimeZone.getTimeZone("Asia/Seoul"));
        return format.format(new Date(millis));
    }
}
