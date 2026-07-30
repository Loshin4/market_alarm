package com.marketalarm.app;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

public class BackgroundSyncWorker extends Worker {
    public BackgroundSyncWorker(@NonNull Context appContext, @NonNull WorkerParameters workerParams) {
        super(appContext, workerParams);
    }

    @NonNull
    @Override
    public Result doWork() {
        try {
            boolean ok = DataRepository.refreshBlocking(getApplicationContext());
            return ok ? Result.success() : Result.retry();
        } catch (Throwable ignored) {
            return Result.retry();
        }
    }
}
