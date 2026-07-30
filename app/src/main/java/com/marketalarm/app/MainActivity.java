package com.marketalarm.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlarmManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private WebView webView;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        NotificationHelper.ensureChannels(this);
        requestNotificationPermission();
        requestExactAlarmPermission();
        webView = new WebView(this);
        setContentView(webView);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new MarketBridge(this), "MarketApp");
        webView.loadUrl("file:///android_asset/index.html");
        SyncScheduler.schedule(this);
        SyncScheduler.runNow(this);
    }

    @Override protected void onDestroy() {
        if (webView != null) webView.destroy();
        super.onDestroy();
    }


    private void requestExactAlarmPermission() {
        if (Build.VERSION.SDK_INT < 31) return;
        try {
            AlarmManager alarmManager = getSystemService(AlarmManager.class);
            if (alarmManager != null && alarmManager.canScheduleExactAlarms()) return;
            Intent intent = new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM);
            intent.setData(Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception ignored) {
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
        }
    }

    private void emitData(String eventsJson, String statusJson) {
        runOnUiThread(() -> webView.evaluateJavascript(
                "window.receiveData(" + JSONObject.quote(eventsJson) + "," + JSONObject.quote(statusJson) + ")", null));
    }

    private void emitStatus(String message, boolean ok) {
        runOnUiThread(() -> webView.evaluateJavascript(
                "window.receiveStatus(" + JSONObject.quote(message) + "," + ok + ")", null));
    }

    private void emitStatusData(String statusJson) {
        runOnUiThread(() -> webView.evaluateJavascript(
                "window.receiveStatusData(" + JSONObject.quote(statusJson) + ")", null));
    }

    public final class MarketBridge {
        private final Context context;
        MarketBridge(Context context) { this.context = context; }

        @JavascriptInterface public String getCachedEvents() { return DataRepository.getCachedEvents(context); }
        @JavascriptInterface public String getCachedStatus() { return DataRepository.getCachedStatus(context); }
        @JavascriptInterface public String getSettings() { return DataRepository.getSettings(context); }
        @JavascriptInterface public boolean shouldRefresh() { return DataRepository.shouldRefresh(context); }
        @JavascriptInterface public long getLastSync() { return DataRepository.getLastSync(context); }
        @JavascriptInterface public void saveSettings(String json) { DataRepository.saveSettings(context, json); }

        @JavascriptInterface public void refreshAll() {
            DataRepository.refreshAll(context, new DataRepository.RefreshCallback() {
                @Override public void onSuccess(String eventsJson, String statusJson, String message) {
                    emitData(eventsJson, statusJson);
                    emitStatus(message, true);
                }
                @Override public void onError(String eventsJson, String statusJson, String message) {
                    emitData(eventsJson, statusJson);
                    emitStatus(message, false);
                }
            });
        }

        @JavascriptInterface public void refreshIndicators() {
            DataRepository.refreshStatusOnly(context, new DataRepository.RefreshCallback() {
                @Override public void onSuccess(String eventsJson, String statusJson, String message) {
                    emitStatusData(statusJson);
                }
                @Override public void onError(String eventsJson, String statusJson, String message) { }
            });
        }

        @JavascriptInterface public void testBackgroundNotification() {
            NotificationHelper.scheduleBackgroundTest(context);
        }

        @JavascriptInterface public boolean isBatteryUnrestricted() {
            if (Build.VERSION.SDK_INT < 23) return true;
            PowerManager manager = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            return manager != null && manager.isIgnoringBatteryOptimizations(context.getPackageName());
        }

        @JavascriptInterface public void openBatterySettings() {
            try {
                if (Build.VERSION.SDK_INT >= 23) {
                    Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    intent.setData(Uri.parse("package:" + context.getPackageName()));
                    startActivity(intent);
                    return;
                }
            } catch (Exception ignored) { }
            try {
                Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                intent.setData(Uri.parse("package:" + context.getPackageName()));
                startActivity(intent);
            } catch (Exception ignored) { }
        }

        @JavascriptInterface public void openUrl(String url) {
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
            catch (Exception ignored) { }
        }
    }
}
