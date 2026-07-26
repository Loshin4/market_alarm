package com.marketalarm.app;

import android.app.AlarmManager;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONObject;

import java.util.List;

public final class NotificationHelper {
    public static final String CHANNEL_ID = "market_events";
    private NotificationHelper() { }

    public static void ensureChannel(Context c) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "증시 중요 일정", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("중요 경제지표와 실적 발표 알림");
            nm.createNotificationChannel(ch);
        }
    }

    public static void scheduleEventReminders(Context c, List<JSONObject> events) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        long now = System.currentTimeMillis();
        int scheduled = 0;
        for (JSONObject e : events) {
            if (e.optInt("importance") < 4 || "released".equals(e.optString("status"))) continue;
            long eventTime = e.optLong("time");
            long[] before = {60 * 60 * 1000L, 10 * 60 * 1000L};
            for (int i = 0; i < before.length; i++) {
                long at = eventTime - before[i];
                if (at <= now || at > now + 120L * 24 * 60 * 60 * 1000) continue;
                int request = Math.abs((e.optString("id") + "-" + i).hashCode());
                Intent intent = new Intent(c, ReminderReceiver.class);
                intent.putExtra("title", e.optString("title"));
                intent.putExtra("minutes", i == 0 ? 60 : 10);
                PendingIntent pi = PendingIntent.getBroadcast(c, request, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
                scheduled++;
                if (scheduled > 80) return;
            }
        }
    }
}
