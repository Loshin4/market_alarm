package com.marketalarm.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class ReminderReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String title = intent.getStringExtra("title");
        String body = intent.getStringExtra("body");
        int id = intent.getIntExtra("notificationId", (int) System.currentTimeMillis());
        NotificationHelper.notify(context, id, title == null ? "증시 일정" : title,
                body == null ? "곧 발표 예정입니다." : body);
    }
}
