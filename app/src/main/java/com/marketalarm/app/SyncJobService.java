package com.marketalarm.app;

import android.app.job.JobParameters;
import android.app.job.JobService;

public class SyncJobService extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        DataRepository.refresh(this, new DataRepository.Callback() {
            @Override
            public void onSuccess(String json, String summary) {
                jobFinished(params, false);
            }

            @Override
            public void onError(String message) {
                jobFinished(params, true);
            }
        });
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
