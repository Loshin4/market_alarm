package com.marketalarm.app;

import android.app.job.JobParameters;
import android.app.job.JobService;

public class SyncJobService extends JobService {
    @Override public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            DataRepository.refreshInBackground(getApplicationContext());
            jobFinished(params, false);
        }).start();
        return true;
    }
    @Override public boolean onStopJob(JobParameters params) { return true; }
}
