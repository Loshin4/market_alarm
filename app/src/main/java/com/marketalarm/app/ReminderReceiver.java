package com.marketalarm.app;

import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import androidx.core.app.NotificationCompat;

public class ReminderReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        NotificationHelper.ensureChannel(context);
        String title = intent.getStringExtra("title");
        int minutes = intent.getIntExtra("minutes", 10);
        Intent open = new Intent(context, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder b = new NotificationCompat.Builder(context, NotificationHelper.CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("⏰ " + minutes + "분 전")
                .setContentText(title)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(title + " 발표가 " + minutes + "분 남았어."))
                .setContentIntent(pi).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH);
        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        nm.notify(Math.abs((title + minutes).hashCode()), b.build());
    }
}
