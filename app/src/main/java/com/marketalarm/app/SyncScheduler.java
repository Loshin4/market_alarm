package com.marketalarm.app;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;

public final class SyncScheduler {
    private static final int JOB_ID = 42601;
    private SyncScheduler() { }

    public static void schedule(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        JobInfo info = new JobInfo.Builder(JOB_ID, new ComponentName(context, SyncJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .setPeriodic(30L * 60L * 1000L)
                .build();
        scheduler.schedule(info);
    }
}
