package com.animeapp.player;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(PlayerScreenPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
