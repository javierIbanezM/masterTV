package com.atvmaster.adbkeeper;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Al arrancar (o al actualizarse la app): un intento inmediato y se programa el trabajo periódico. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Keeper.Result r = Keeper.apply(context);   // puede fallar si el Wi-Fi aún no está: el trabajo reintenta
        Keeper.log(context, "arranque: " + r.text);
        KeepJob.schedule(context);
    }
}
