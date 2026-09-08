package com.moonyoung.sttbench.mobile_bench

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager

class BenchmarkForegroundService : Service() {
    private var wakeLock: PowerManager.WakeLock? = null
    private var subtitle = "준비 중"
    private var progress = 0

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startBenchmark(intent)
            ACTION_UPDATE -> {
                progress = intent.getIntExtra("progress", progress).coerceIn(0, 100)
                subtitle = intent.getStringExtra("subtitle") ?: subtitle
                notificationManager().notify(NOTIFICATION_ID, notification(false))
            }
            ACTION_CANCEL -> {
                subtitle = "취소 요청 중"
                notificationManager().notify(NOTIFICATION_ID, notification(false))
                (application as BenchmarkApplication).bridge.notifyCancelRequested()
            }
            ACTION_FINISH -> finishBenchmark(intent.getBooleanExtra("success", false))
        }
        return START_NOT_STICKY
    }

    private fun startBenchmark(intent: Intent) {
        subtitle = intent.getStringExtra("subtitle") ?: "준비 중"
        progress = 0
        val currentNotification = notification(false)
        when {
            // `specialUse`, not `mediaProcessing`: Android 15 enforces a
            // system-wide cumulative daily execution budget on the
            // `dataSync`/`mediaProcessing` FGS types (Service.onTimeout()
            // fires once it's spent, forcing this service to stop — that
            // showed up as batches getting cut off earlier and earlier
            // through a day of repeated benchmark runs). `specialUse` is not
            // one of the time-limited types on this Android version, so a
            // long-running batch isn't budget-capped the same way.
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE -> {
                startForeground(
                    NOTIFICATION_ID,
                    currentNotification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
                )
            }
            else -> startForeground(NOTIFICATION_ID, currentNotification)
        }
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = power.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "$packageName:stt-benchmark",
        ).apply {
            setReferenceCounted(false)
            acquire(MAX_RUN_MILLIS)
        }
    }

    private fun finishBenchmark(success: Boolean) {
        releaseWakeLock()
        stopForeground(STOP_FOREGROUND_REMOVE)
        notificationManager().notify(
            COMPLETION_NOTIFICATION_ID,
            notification(completed = true, success = success),
        )
        stopSelf()
    }

    private fun notification(completed: Boolean, success: Boolean = false): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP,
            ),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION") Notification.Builder(this)
        }
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentIntent(openIntent)
            .setOngoing(!completed)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_PROGRESS)

        if (completed) {
            builder
                .setContentTitle(if (success) "STT 벤치마크 완료" else "STT 벤치마크 종료")
                .setContentText("앱에서 결과를 확인하세요")
                .setAutoCancel(true)
        } else {
            val cancelIntent = PendingIntent.getService(
                this,
                1,
                Intent(this, BenchmarkForegroundService::class.java).setAction(ACTION_CANCEL),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            builder
                .setContentTitle("STT 벤치마크 실행 중")
                .setContentText(subtitle)
                .setProgress(100, progress, false)
                .addAction(
                    Notification.Action.Builder(
                        android.R.drawable.ic_menu_close_clear_cancel,
                        "취소",
                        cancelIntent,
                    ).build(),
                )
        }
        return builder.build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        notificationManager().createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "벤치마크 실행",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "백그라운드 STT 벤치마크 진행 상태"
                setSound(null, null)
            },
        )
    }

    private fun notificationManager(): NotificationManager =
        getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    private fun releaseWakeLock() {
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        (application as BenchmarkApplication).bridge.notifyExecutionExpired()
        finishBenchmark(false)
    }

    override fun onDestroy() {
        releaseWakeLock()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_START = "sttbench.action.START"
        const val ACTION_UPDATE = "sttbench.action.UPDATE"
        const val ACTION_CANCEL = "sttbench.action.CANCEL"
        const val ACTION_FINISH = "sttbench.action.FINISH"
        private const val CHANNEL_ID = "stt_benchmark_execution"
        private const val NOTIFICATION_ID = 41001
        private const val COMPLETION_NOTIFICATION_ID = 41002
        private const val MAX_RUN_MILLIS = 6L * 60 * 60 * 1000
    }
}
