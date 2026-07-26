package com.marketalarm.app;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

import org.json.JSONArray;
import org.json.JSONObject;

public final class AlarmScheduler {
    private AlarmScheduler() { }

    public static void scheduleUpcoming(Context context, JSONArray events) {
        AlarmManager manager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (manager == null) return;
        long now = System.currentTimeMillis();
        long max = now + 45L * 24L * 60L * 60L * 1000L;
        for (int i = 0; i < events.length(); i++) {
            JSONObject event = events.optJSONObject(i);
            if (event == null || event.optInt("importance", 1) < 4) continue;
            long time = event.optLong("time", 0L);
            if (time <= now || time > max) continue;
            scheduleOne(context, manager, event, time - 60L * 60L * 1000L, "1시간 전");
            scheduleOne(context, manager, event, time - 10L * 60L * 1000L, "10분 전");
        }
    }

    private static void scheduleOne(Context context, AlarmManager manager, JSONObject event,
                                    long trigger, String label) {
        if (trigger <= System.currentTimeMillis()) return;
        String id = event.optString("id", "event");
        int requestCode = (id + label).hashCode();
        Intent intent = new Intent(context, ReminderReceiver.class);
        intent.putExtra("title", "⏰ " + event.optString("title", "증시 일정"));
        intent.putExtra("body", label + " · " + event.optString("source", "공식 일정"));
        intent.putExtra("notificationId", requestCode);
        PendingIntent pi = PendingIntent.getBroadcast(
                context, requestCode, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        manager.setWindow(AlarmManager.RTC_WAKEUP, trigger, 10L * 60L * 1000L, pi);
    }
}
