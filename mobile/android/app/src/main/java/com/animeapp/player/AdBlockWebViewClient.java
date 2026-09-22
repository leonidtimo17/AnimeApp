package com.animeapp.player;

import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

import java.io.ByteArrayInputStream;

/**
 * Блокировка рекламы в плеере Kodik. Пока он открыт (флаг включает PlayerScreenPlugin.adblock),
 * WebView пропускает только само приложение и серверы Kodik (плеер и видео), а рекламные сети и счётчики — нет.
 * Белый список, а не чёрный: рекламные домены у Kodik постоянно меняются, бывают и со случайными именами.
 */
public class AdBlockWebViewClient extends BridgeWebViewClient {
    static volatile boolean enabled = false;

    private static final String[] ALLOWED = {
        "localhost",                                   // само приложение
        "kodikplayer.com", "kodik.info", "kodik.biz", "kodik.cc", "kodik.online",
        "kodikres.com", "kodik-storage.com", "solodcdn.com",
        "shikimori.io",                                // аватары в обсуждении серии
    };

    public AdBlockWebViewClient(Bridge bridge) {
        super(bridge);
    }

    static boolean allowed(Uri uri) {
        String scheme = uri.getScheme();
        if (scheme == null || !(scheme.equals("http") || scheme.equals("https"))) return true;
        String host = uri.getHost();
        if (host == null) return true;
        for (String h : ALLOWED) {
            if (host.equals(h) || host.endsWith("." + h)) return true;
        }
        return false;
    }

    @Override
    public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        if (enabled && !allowed(request.getUrl())) {
            return new WebResourceResponse("text/plain", "utf-8", 403, "Blocked", null,
                new ByteArrayInputStream(new byte[0]));
        }
        return super.shouldInterceptRequest(view, request);
    }
}
