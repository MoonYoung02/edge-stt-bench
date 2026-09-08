package com.moonyoung.sttbench.mobile_bench

import android.app.ActivityManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Debug
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.Process
import android.provider.MediaStore
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

class BenchmarkPlatformBridge(
    private val application: BenchmarkApplication,
    messenger: BinaryMessenger,
) {
    private val channel = MethodChannel(
        messenger,
        CHANNEL_NAME,
        io.flutter.plugin.common.StandardMethodCodec.INSTANCE,
        messenger.makeBackgroundTaskQueue(),
    )
    private var lastThermalReadMs = 0L
    private var lastThermalHeadroom: Float? = null

    init {
        channel.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "getDeviceInfo" -> result.success(deviceInfo())
                    "getMetricsSnapshot" -> result.success(metricsSnapshot())
                    "startBackgroundExecution" -> {
                        val intent = Intent(application, BenchmarkForegroundService::class.java)
                            .setAction(BenchmarkForegroundService.ACTION_START)
                            .putExtra("runId", call.argument<String>("runId"))
                            .putExtra("title", call.argument<String>("title"))
                            .putExtra("subtitle", call.argument<String>("subtitle"))
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                            application.startForegroundService(intent)
                        } else {
                            application.startService(intent)
                        }
                        result.success(null)
                    }
                    "updateBackgroundExecution" -> {
                        application.startService(
                            Intent(application, BenchmarkForegroundService::class.java)
                                .setAction(BenchmarkForegroundService.ACTION_UPDATE)
                                .putExtra("progress", call.argument<Int>("progress") ?: 0)
                                .putExtra("subtitle", call.argument<String>("subtitle")),
                        )
                        result.success(null)
                    }
                    "finishBackgroundExecution" -> {
                        application.startService(
                            Intent(application, BenchmarkForegroundService::class.java)
                                .setAction(BenchmarkForegroundService.ACTION_FINISH)
                                .putExtra("success", call.argument<Boolean>("success") == true),
                        )
                        result.success(null)
                    }
                    "exportResult" -> {
                        val source = call.argument<String>("sourcePath")
                            ?: error("sourcePath is required")
                        val name = call.argument<String>("fileName")
                            ?: error("fileName is required")
                        result.success(exportResult(source, name))
                    }
                    else -> result.notImplemented()
                }
            } catch (error: Throwable) {
                result.error("PLATFORM_ERROR", error.message, error.stackTraceToString())
            }
        }
    }

    fun notifyCancelRequested() {
        Handler(Looper.getMainLooper()).post {
            channel.invokeMethod("backgroundCancelRequested", null)
        }
    }

    fun notifyExecutionExpired() {
        Handler(Looper.getMainLooper()).post {
            channel.invokeMethod("backgroundExecutionExpired", null)
        }
    }

    private fun deviceInfo(): Map<String, Any?> {
        val memory = ActivityManager.MemoryInfo()
        (application.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager)
            .getMemoryInfo(memory)
        return mapOf(
            "platform" to "android",
            "manufacturer" to Build.MANUFACTURER,
            "model" to Build.MODEL,
            "osVersion" to "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})",
            "logicalCpuCores" to Runtime.getRuntime().availableProcessors(),
            "totalMemoryBytes" to memory.totalMem,
        )
    }

    private fun metricsSnapshot(): Map<String, Any?> {
        val power = application.getSystemService(Context.POWER_SERVICE) as PowerManager
        val batteryIntent = application.registerReceiver(
            null,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED),
        )
        val temperatureTenths = batteryIntent?.getIntExtra(
            BatteryManager.EXTRA_TEMPERATURE,
            Int.MIN_VALUE,
        ) ?: Int.MIN_VALUE
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val plugged = batteryIntent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0

        val now = android.os.SystemClock.elapsedRealtime()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && now - lastThermalReadMs >= 1000) {
            lastThermalReadMs = now
            lastThermalHeadroom = power.getThermalHeadroom(0).takeIf { it.isFinite() }
        }

        return mapOf(
            "processCpuTimeMs" to Process.getElapsedCpuTime().toDouble(),
            "memoryBytes" to Debug.getPss() * 1024L,
            "nativeHeapBytes" to Debug.getNativeHeapAllocatedSize(),
            "logicalCpuCores" to Runtime.getRuntime().availableProcessors(),
            "thermalStatus" to if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                thermalStatusName(power.currentThermalStatus)
            } else {
                null
            },
            "thermalHeadroom" to lastThermalHeadroom,
            "batteryTemperatureC" to if (temperatureTenths == Int.MIN_VALUE) {
                null
            } else {
                temperatureTenths / 10.0
            },
            "batteryLevelPercent" to if (level >= 0 && scale > 0) level * 100.0 / scale else null,
            "charging" to (plugged != 0),
            "screenInteractive" to power.isInteractive,
        )
    }

    private fun thermalStatusName(status: Int): String = when (status) {
        PowerManager.THERMAL_STATUS_NONE -> "none"
        PowerManager.THERMAL_STATUS_LIGHT -> "light"
        PowerManager.THERMAL_STATUS_MODERATE -> "moderate"
        PowerManager.THERMAL_STATUS_SEVERE -> "severe"
        PowerManager.THERMAL_STATUS_CRITICAL -> "critical"
        PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency"
        PowerManager.THERMAL_STATUS_SHUTDOWN -> "shutdown"
        else -> "unknown"
    }

    private fun exportResult(sourcePath: String, fileName: String): String {
        val source = File(sourcePath)
        require(source.isFile) { "Result file does not exist: $sourcePath" }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                put(MediaStore.Downloads.MIME_TYPE, "application/json")
                put(MediaStore.Downloads.RELATIVE_PATH, "Download/STTBench/results")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val resolver = application.contentResolver
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: error("Unable to create export file")
            try {
                resolver.openOutputStream(uri)?.use { output ->
                    FileInputStream(source).use { input -> input.copyTo(output) }
                } ?: error("Unable to open export file")
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
                return "Download/STTBench/results/$fileName"
            } catch (error: Throwable) {
                resolver.delete(uri, null, null)
                throw error
            }
        }

        @Suppress("DEPRECATION")
        val directory = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            "STTBench/results",
        )
        directory.mkdirs()
        val target = File(directory, fileName)
        FileInputStream(source).use { input ->
            FileOutputStream(target).use { output -> input.copyTo(output) }
        }
        return target.absolutePath
    }

    companion object {
        const val CHANNEL_NAME = "com.moonyoung.sttbench/platform"
    }
}
