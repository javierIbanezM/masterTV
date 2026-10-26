package com.atvmaster.adbkeeper;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Pantalla de estado. Con el extra «silent» = true hace un intento y se cierra sin mostrar nada. */
public class MainActivity extends Activity {
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        KeepJob.schedule(this);
        Keeper.Result r = Keeper.apply(this);
        Keeper.log(this, "al abrir: " + r.text);
        if (getIntent().getBooleanExtra("silent", false)) {
            finish();
            return;
        }

        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("ADB Keeper");
        title.setTextSize(24);
        root.addView(title);

        status = new TextView(this);
        status.setTextSize(16);
        status.setPadding(0, pad, 0, pad);
        root.addView(status);

        Button again = new Button(this);
        again.setText("Comprobar ahora");
        again.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Keeper.Result rr = Keeper.apply(MainActivity.this);
                Keeper.log(MainActivity.this, "manual: " + rr.text);
                refresh();
            }
        });
        root.addView(again);

        setContentView(root);
        refresh();
    }

    private void refresh() {
        boolean perm = Keeper.hasPermission(this);
        boolean on = Keeper.wifiDebugOn(this);
        status.setText("Permiso WRITE_SECURE_SETTINGS: " + (perm ? "concedido" : "FALTA") + "\n"
                + "Depuración inalámbrica: " + (on ? "activa" : "apagada") + "\n"
                + "Wi-Fi/Ethernet conectado: " + (Keeper.onLocalNetwork(this) ? "sí" : "no") + "\n\n"
                + "Última comprobación:\n" + Keeper.lastLog(this) + "\n\n"
                + "Al arrancar el dispositivo, y cada 15 minutos con red, vuelve a activar la depuración "
                + "inalámbrica si estuviera apagada.\n\n"
                + (perm ? "" : "Concede el permiso desde el PC:\nadb shell pm grant " + getPackageName()
                + " android.permission.WRITE_SECURE_SETTINGS"));
    }
}
