package com.atvmaster.adbkeeper;

import android.content.ContentResolver;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.provider.Settings;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Lógica única: deja encendida la depuración inalámbrica y sin caducidad de autorización. */
final class Keeper {
    static final String PERMISSION = "android.permission.WRITE_SECURE_SETTINGS";
    static final String WIFI_DEBUG = "adb_wifi_enabled";               // «Depuración inalámbrica» (Android 11+)
    static final String NO_EXPIRY = "adb_allowed_connection_time";     // 0 = la autorización no caduca

    /** Resultado de un intento: si quedó hecho, si conviene reintentar luego y un texto legible. */
    static final class Result {
        final boolean done;
        final boolean retry;
        final String text;

        Result(boolean done, boolean retry, String text) {
            this.done = done;
            this.retry = retry;
            this.text = text;
        }
    }

    private Keeper() {}

    static boolean hasPermission(Context c) {
        return c.checkSelfPermission(PERMISSION) == PackageManager.PERMISSION_GRANTED;
    }

    /** Wi-Fi o Ethernet activos. Android apaga solo la depuración inalámbrica si se activa sin red. */
    static boolean onLocalNetwork(Context c) {
        ConnectivityManager cm = (ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE);
        Network n = cm.getActiveNetwork();
        if (n == null) return false;
        NetworkCapabilities nc = cm.getNetworkCapabilities(n);
        return nc != null && (nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                || nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET));
    }

    static boolean wifiDebugOn(Context c) {
        return Settings.Global.getInt(c.getContentResolver(), WIFI_DEBUG, 0) == 1;
    }

    /** Un intento. Es barato (dos lecturas y, si hace falta, dos escrituras): se puede llamar a menudo. */
    static Result apply(Context c) {
        if (!hasPermission(c)) {
            return new Result(false, false, "Falta el permiso WRITE_SECURE_SETTINGS: concédelo con adb "
                    + "(adb shell pm grant " + c.getPackageName() + " " + PERMISSION + ")");
        }
        ContentResolver cr = c.getContentResolver();
        try {
            // Sin las opciones de desarrollador / ADB activos no hay nada que mantener.
            if (Settings.Global.getInt(cr, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) != 1) {
                Settings.Global.putInt(cr, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 1);
            }
            if (Settings.Global.getInt(cr, Settings.Global.ADB_ENABLED, 0) != 1) {
                Settings.Global.putInt(cr, Settings.Global.ADB_ENABLED, 1);
            }
            Settings.Global.putLong(cr, NO_EXPIRY, 0L);
            if (wifiDebugOn(c)) {
                return new Result(true, false, "Depuración inalámbrica ya activa");
            }
            if (!onLocalNetwork(c)) {
                return new Result(false, true, "Sin Wi-Fi todavía: se reintentará");
            }
            Settings.Global.putInt(cr, WIFI_DEBUG, 1);
            return wifiDebugOn(c)
                    ? new Result(true, false, "Depuración inalámbrica activada")
                    : new Result(false, true, "El sistema no la activó: se reintentará");
        } catch (SecurityException e) {
            return new Result(false, false, "Permiso denegado: " + e.getMessage());
        } catch (RuntimeException e) {
            return new Result(false, true, "Error: " + e);
        }
    }

    // ------------------------------------------------------------ registro de la última comprobación

    private static SharedPreferences prefs(Context c) {
        // Almacenamiento protegido del dispositivo: disponible incluso antes de desbloquear tras el arranque.
        return c.createDeviceProtectedStorageContext().getSharedPreferences("keeper", Context.MODE_PRIVATE);
    }

    static void log(Context c, String text) {
        String when = new SimpleDateFormat("dd/MM HH:mm:ss", Locale.getDefault()).format(new Date());
        prefs(c).edit().putString("last", when + " · " + text).apply();
        // También al registro del sistema: se puede leer desde el PC con `adb logcat -s AdbKeeper`.
        android.util.Log.i("AdbKeeper", text);
    }

    static String lastLog(Context c) {
        return prefs(c).getString("last", "(todavía no se ha ejecutado)");
    }
}
