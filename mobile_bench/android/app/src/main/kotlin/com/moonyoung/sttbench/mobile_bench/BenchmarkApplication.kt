package com.moonyoung.sttbench.mobile_bench

import io.flutter.app.FlutterApplication
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.embedding.engine.dart.DartExecutor

class BenchmarkApplication : FlutterApplication() {
    lateinit var flutterEngine: FlutterEngine
        private set
    lateinit var bridge: BenchmarkPlatformBridge
        private set

    override fun onCreate() {
        super.onCreate()
        flutterEngine = FlutterEngine(this)
        bridge = BenchmarkPlatformBridge(
            application = this,
            messenger = flutterEngine.dartExecutor.binaryMessenger,
        )
        flutterEngine.dartExecutor.executeDartEntrypoint(
            DartExecutor.DartEntrypoint.createDefault(),
        )
        FlutterEngineCache.getInstance().put(ENGINE_ID, flutterEngine)
    }

    companion object {
        const val ENGINE_ID = "stt_benchmark_engine"
    }
}
