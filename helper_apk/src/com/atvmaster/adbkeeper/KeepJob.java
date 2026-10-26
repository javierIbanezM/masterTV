package com.atvmaster.adbkeeper;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/** Trabajo en segundo plano: comprueba y, si hace falta, reactiva la depuración inalámbrica. */
public class KeepJob extends JobService {
    private static final int PERIODIC_ID = 1;   // cada 15 min (mínimo que permite Android); sobrevive a reinicios
    private static final int NOW_ID = 2;        // un intento inmediato (con reintentos si aún no hay Wi-Fi)

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                Keeper.Result r = Keeper.apply(KeepJob.this);
                Keeper.log(KeepJob.this, r.text);
                jobFinished(params, r.retry);   // retry = true -> Android lo reprograma con espera creciente
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }

    /** Programa el trabajo periódico (una sola vez) y lanza un intento inmediato. */
    static void schedule(Context c) {
        JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        ComponentName me = new ComponentName(c, KeepJob.class);
        if (js.getPendingJob(PERIODIC_ID) == null) {
            js.schedule(new JobInfo.Builder(PERIODIC_ID, me)
                    .setPeriodic(15 * 60 * 1000L)
                    .setPersisted(true)
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .build());
        }
        js.schedule(new JobInfo.Builder(NOW_ID, me)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setBackoffCriteria(20 * 1000L, JobInfo.BACKOFF_POLICY_LINEAR)
                .setOverrideDeadline(2000L)
                .build());
    }
}
