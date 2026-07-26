package com.marketalarm.app;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

public final class Storage {
    private static final String PREFS = "market_alarm";
    private static final String EVENTS = "events_json";
    private static final String SETTINGS = "settings_json";

    private Storage() { }

    public static String getEvents(Context context) {
        return prefs(context).getString(EVENTS, "[]");
    }

    public static void saveEvents(Context context, String json) {
        prefs(context).edit().putString(EVENTS, json).apply();
    }

    public static String getSettings(Context context) {
        String saved = prefs(context).getString(SETTINGS, "");
        if (saved != null && !saved.trim().isEmpty()) return saved;
        try {
            JSONObject defaults = new JSONObject();
            defaults.put("alphaKey", "");
            defaults.put("dartKey", "");
            defaults.put("watchlist", "NVDA,MSFT,GOOGL,AMZN,META");
            defaults.put("showMinor", false);
            return defaults.toString();
        } catch (Exception e) {
            return "{}";
        }
    }

    public static void saveSettings(Context context, String json) {
        prefs(context).edit().putString(SETTINGS, json).apply();
    }

    public static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
