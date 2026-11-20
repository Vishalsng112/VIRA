package com.vira.link

import android.app.ActivityManager
import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.Process
import android.os.StatFs
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val channelName = "com.vira.link/device"
    private val executor = Executors.newSingleThreadExecutor()

    private var lastQueryTime: Long = 0L
    private var currentPackage: String? = null
    private var currentStart: Long = 0L
    private val labelCache = HashMap<String, String>()

    private var lastSessionQueryTime: Long = 0L
    private var sessionScreenOn: Boolean = false
    private var sessionScreenOnStart: Long = 0L
    private var sessionStartedAt: Long = 0L

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "usagePermission" -> result.success(hasUsagePermission())
                    "openUsageSettings" -> result.success(openUsageSettings())
                    "appUsage" -> {
                        val lookback = (call.argument<Number>("lookback_ms") ?: 300000L).toLong()
                        executor.execute {
                            try {
                                val usage = collectAppUsage(lookback)
                                runOnUiThread { result.success(usage) }
                            } catch (error: Exception) {
                                runOnUiThread {
                                    result.error("usage_error", error.message, null)
                                }
                            }
                        }
                    }
                    "sessionStats" -> {
                        val lookback = (call.argument<Number>("lookback_ms") ?: 300000L).toLong()
                        executor.execute {
                            try {
                                val stats = collectSessionStats(lookback)
                                runOnUiThread { result.success(stats) }
                            } catch (error: Exception) {
                                runOnUiThread {
                                    result.error("session_error", error.message, null)
                                }
                            }
                        }
                    }
                    "battery" -> result.success(batteryState())
                    "health" -> result.success(healthState())
                    else -> result.notImplemented()
                }
            }
    }

    private fun hasUsagePermission(): Boolean {
        val appOps = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            appOps.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                packageName,
            )
        } else {
            @Suppress("DEPRECATION")
            appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                packageName,
            )
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun openUsageSettings(): Boolean {
        return try {
            val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(intent)
            true
        } catch (_: Exception) {
            false
        }
    }

    /// Returns aggregated foreground time since the previous poll. The tracker
    /// keeps the open foreground segment across calls, so an app that stays in
    /// front is counted in each interval without double counting.
    private fun collectAppUsage(lookbackMs: Long): List<Map<String, Any>> {
        if (!hasUsagePermission()) return emptyList()

        val now = System.currentTimeMillis()
        if (lastQueryTime == 0L) {
            lastQueryTime = now - lookbackMs
        }
        val manager = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val events = manager.queryEvents(lastQueryTime, now)
        val durations = HashMap<String, Long>()
        val lastUsed = HashMap<String, Long>()
        val event = UsageEvents.Event()

        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val pkg = event.packageName ?: continue
            if (pkg == packageName) continue
            val timestamp = event.timeStamp
            when (event.eventType) {
                UsageEvents.Event.MOVE_TO_FOREGROUND -> {
                    if (currentPackage != null && currentPackage != pkg) {
                        val previous = currentPackage!!
                        durations[previous] =
                            (durations[previous] ?: 0L) + (timestamp - currentStart).coerceAtLeast(0L)
                    }
                    if (currentPackage != pkg) {
                        currentPackage = pkg
                        currentStart = timestamp
                    }
                    lastUsed[pkg] = maxOf(lastUsed[pkg] ?: 0L, timestamp)
                }
                UsageEvents.Event.MOVE_TO_BACKGROUND,
                UsageEvents.Event.ACTIVITY_STOPPED -> {
                    if (currentPackage == pkg) {
                        durations[pkg] =
                            (durations[pkg] ?: 0L) + (timestamp - currentStart).coerceAtLeast(0L)
                        currentPackage = null
                    }
                }
            }
        }

        if (currentPackage != null) {
            val pkg = currentPackage!!
            durations[pkg] = (durations[pkg] ?: 0L) + (now - currentStart).coerceAtLeast(0L)
            currentStart = now
        }
        lastQueryTime = now

        return durations.entries
            .filter { it.value >= 1000L }
            .sortedByDescending { it.value }
            .map { entry ->
                mapOf(
                    "package" to entry.key,
                    "label" to appLabel(entry.key),
                    "foreground_ms" to entry.value,
                    "last_used_ms" to (lastUsed[entry.key] ?: now),
                )
            }
    }

    private fun collectSessionStats(lookbackMs: Long): Map<String, Any> {
        if (!hasUsagePermission()) return emptyMap()

        val now = System.currentTimeMillis()
        if (lastSessionQueryTime == 0L) {
            lastSessionQueryTime = now - lookbackMs
            val power = getSystemService(Context.POWER_SERVICE) as PowerManager
            sessionScreenOn = power.isInteractive
            sessionScreenOnStart = if (sessionScreenOn) lastSessionQueryTime else 0L
            sessionStartedAt = sessionScreenOnStart
        }
        val manager = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val events = manager.queryEvents(lastSessionQueryTime, now)
        val event = UsageEvents.Event()
        var interactiveMs = 0L
        var screenOnEvents = 0
        var screenOffEvents = 0
        var unlocks = 0
        var interactions = 0

        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val timestamp = event.timeStamp
            when (event.eventType) {
                UsageEvents.Event.SCREEN_INTERACTIVE -> {
                    if (!sessionScreenOn) {
                        sessionScreenOn = true
                        sessionScreenOnStart = timestamp
                        sessionStartedAt = timestamp
                        screenOnEvents += 1
                    }
                }
                UsageEvents.Event.SCREEN_NON_INTERACTIVE -> {
                    if (sessionScreenOn) {
                        interactiveMs += (timestamp - sessionScreenOnStart).coerceAtLeast(0L)
                        sessionScreenOn = false
                        sessionStartedAt = 0L
                        screenOffEvents += 1
                    }
                }
                UsageEvents.Event.KEYGUARD_HIDDEN -> unlocks += 1
                UsageEvents.Event.USER_INTERACTION -> interactions += 1
            }
        }

        var currentSessionMs = 0L
        if (sessionScreenOn) {
            val segment = (now - sessionScreenOnStart).coerceAtLeast(0L)
            interactiveMs += segment
            sessionScreenOnStart = now
            currentSessionMs = (now - sessionStartedAt).coerceAtLeast(0L)
        }
        lastSessionQueryTime = now

        return mapOf(
            "interactive_ms" to interactiveMs,
            "screen_on_events" to screenOnEvents,
            "screen_off_events" to screenOffEvents,
            "unlocks" to unlocks,
            "interactions" to interactions,
            "current_session_ms" to currentSessionMs,
            "screen_on" to sessionScreenOn,
            "window_seconds" to (lookbackMs / 1000L),
        )
    }

    private fun batteryState(): Map<String, Any> {
        val result = HashMap<String, Any>()
        val manager = getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val level = manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        if (level in 0..100) result["level_percent"] = level
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            result["charging"] = manager.isCharging
        }
        try {
            val intent = registerReceiver(
                null,
                IntentFilter(Intent.ACTION_BATTERY_CHANGED),
            )
            if (intent != null) {
                val temperature = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1)
                if (temperature > 0) result["temperature_c"] = temperature / 10.0
                val plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)
                result["plugged"] = when (plugged) {
                    BatteryManager.BATTERY_PLUGGED_AC -> "ac"
                    BatteryManager.BATTERY_PLUGGED_USB -> "usb"
                    BatteryManager.BATTERY_PLUGGED_WIRELESS -> "wireless"
                    else -> "none"
                }
                val health = intent.getIntExtra(BatteryManager.EXTRA_HEALTH, -1)
                result["health"] = when (health) {
                    BatteryManager.BATTERY_HEALTH_GOOD -> "good"
                    BatteryManager.BATTERY_HEALTH_OVERHEAT -> "overheat"
                    BatteryManager.BATTERY_HEALTH_DEAD -> "dead"
                    BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE -> "over_voltage"
                    BatteryManager.BATTERY_HEALTH_COLD -> "cold"
                    else -> "unknown"
                }
            }
        } catch (_: Exception) {
            // Partial battery data is still useful.
        }
        return result
    }

    private fun healthState(): Map<String, Any> {
        val result = HashMap<String, Any>()
        try {
            val stat = StatFs(Environment.getDataDirectory().path)
            result["storage_total_bytes"] = stat.blockCountLong * stat.blockSizeLong
            result["storage_free_bytes"] = stat.availableBlocksLong * stat.blockSizeLong
        } catch (_: Exception) {
            // Storage data is optional.
        }
        try {
            val manager = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val memory = ActivityManager.MemoryInfo()
            manager.getMemoryInfo(memory)
            result["memory_total_bytes"] = memory.totalMem
            result["memory_available_bytes"] = memory.availMem
        } catch (_: Exception) {
            // Memory data is optional.
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val power = getSystemService(Context.POWER_SERVICE) as PowerManager
                result["thermal_status"] = when (power.currentThermalStatus) {
                    PowerManager.THERMAL_STATUS_NONE -> "none"
                    PowerManager.THERMAL_STATUS_LIGHT -> "light"
                    PowerManager.THERMAL_STATUS_MODERATE -> "moderate"
                    PowerManager.THERMAL_STATUS_SEVERE -> "severe"
                    PowerManager.THERMAL_STATUS_CRITICAL -> "critical"
                    PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency"
                    PowerManager.THERMAL_STATUS_SHUTDOWN -> "shutdown"
                    else -> "unknown"
                }
            } catch (_: Exception) {
                // Thermal data is optional.
            }
        }
        val battery = batteryState()
        if (battery["temperature_c"] != null) {
            result["battery_temperature_c"] = battery["temperature_c"]!!
        }
        return result
    }

    private fun appLabel(packageName: String): String {
        labelCache[packageName]?.let { return it }
        val label = try {
            val info = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(info).toString()
        } catch (_: PackageManager.NameNotFoundException) {
            packageName
        }
        labelCache[packageName] = label
        return label
    }
}
