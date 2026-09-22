package com.animeapp.player;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.view.Window;
import android.view.WindowManager;

import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Экран во время просмотра: полноэкранный режим без строки состояния и навигации,
 * экран не гаснет; открытие ссылок во внешнем браузере (вход через Shikimori).
 * (Полноэкранный режим из веба в Capacitor не работает — он его сразу отменяет.)
 */
@CapacitorPlugin(name = "PlayerScreen")
public class PlayerScreenPlugin extends Plugin {

    /** fullscreen({on: boolean}) — спрятать/показать системные панели. */
    @PluginMethod
    public void fullscreen(PluginCall call) {
        final boolean on = Boolean.TRUE.equals(call.getBoolean("on", true));
        final Activity activity = getActivity();
        activity.runOnUiThread(() -> {
            Window window = activity.getWindow();
            WindowInsetsControllerCompat ctl = WindowCompat.getInsetsController(window, window.getDecorView());
            if (on) {
                // Панели появляются на время по свайпу от края и сами прячутся обратно
                ctl.setSystemBarsBehavior(WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                ctl.hide(WindowInsetsCompat.Type.systemBars());
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            } else {
                ctl.show(WindowInsetsCompat.Type.systemBars());
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            }
            call.resolve();
        });
    }

    /** openUrl({url}) — открыть страницу в браузере телефона/планшета. */
    @PluginMethod
    public void openUrl(PluginCall call) {
        String url = call.getString("url");
        if (url == null || !(url.startsWith("https://") || url.startsWith("http://"))) {
            call.reject("Неверная ссылка");
            return;
        }
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getActivity().startActivity(intent);
        call.resolve();
    }
}
