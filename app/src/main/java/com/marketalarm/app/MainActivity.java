package com.marketalarm.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        NotificationHelper.createChannel(this);
        requestNotificationPermission();
        SyncScheduler.schedule(this);

        webView = new WebView(this);
        setContentView(webView);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        webView.addJavascriptInterface(new AppBridge(), "MarketApp");
        webView.loadUrl("file:///android_asset/index.html");
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
        }
    }

    private void sendEventsToWeb(String json) {
        if (webView == null) return;
        String script = "window.receiveEvents(" + JSONObject.quote(json) + ");";
        runOnUiThread(() -> webView.evaluateJavascript(script, null));
    }

    private void sendStatusToWeb(String message, boolean ok) {
        if (webView == null) return;
        String script = "window.receiveStatus(" + JSONObject.quote(message) + "," + ok + ");";
        runOnUiThread(() -> webView.evaluateJavascript(script, null));
    }

    public class AppBridge {
        @JavascriptInterface
        public String getCachedEvents() {
            return Storage.getEvents(MainActivity.this);
        }

        @JavascriptInterface
        public String getSettings() {
            return Storage.getSettings(MainActivity.this);
        }

        @JavascriptInterface
        public void saveSettings(String json) {
            Storage.saveSettings(MainActivity.this, json);
            sendStatusToWeb("설정을 저장했어요.", true);
        }

        @JavascriptInterface
        public void refreshAll() {
            sendStatusToWeb("공식 일정을 불러오는 중...", true);
            DataRepository.refresh(MainActivity.this, new DataRepository.Callback() {
                @Override
                public void onSuccess(String json, String summary) {
                    sendEventsToWeb(json);
                    sendStatusToWeb(summary, true);
                }

                @Override
                public void onError(String message) {
                    sendStatusToWeb(message, false);
                }
            });
        }

        @JavascriptInterface
        public void openUrl(String url) {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception ignored) { }
        }
    }
}
