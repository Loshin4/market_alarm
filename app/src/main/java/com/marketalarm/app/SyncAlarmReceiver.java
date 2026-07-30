package com.marketalarm.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class SyncAlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        final PendingResult pendingResult = goAsync();
        new Thread(() -> {
            try {
                DataRepository.refreshBlocking(context.getApplicationContext());
            } catch (Throwable ignored) {
            } finally {
                try {
                    SyncScheduler.schedule(context.getApplicationContext());
                } catch (Throwable ignored) {
                }
                pendingResult.finish();
            }
        }, "market-sync-alarm").start();
    }
}
