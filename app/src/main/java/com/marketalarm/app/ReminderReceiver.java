package com.marketalarm.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class ReminderReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String title = intent.getStringExtra("title");
        if (title == null || title.trim().isEmpty()) title = "중요 증시 일정";
        int minutes = intent.getIntExtra("minutes", 10);
        NotificationHelper.postReminder(context, title, minutes);
    }
}
