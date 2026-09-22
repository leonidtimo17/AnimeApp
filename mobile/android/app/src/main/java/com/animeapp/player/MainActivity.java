package com.animeapp.player;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(PlayerScreenPlugin.class);
        super.onCreate(savedInstanceState);
        // Свой обработчик запросов WebView: блокировка рекламы в плеере Kodik (остальное — как у Capacitor)
        bridge.setWebViewClient(new AdBlockWebViewClient(bridge));
    }
}
