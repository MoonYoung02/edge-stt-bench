import 'dart:io';

import 'package:flutter/services.dart';

import 'benchmark_run.dart';

class PlatformBridge {
  PlatformBridge();

  static const MethodChannel _channel = MethodChannel(
    'com.moonyoung.sttbench/platform',
  );

  Future<void> Function()? onCancelRequested;
  Future<void> Function()? onExecutionExpired;

  void initialize() {
    _channel.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'backgroundCancelRequested':
          await onCancelRequested?.call();
        case 'backgroundExecutionExpired':
          await onExecutionExpired?.call();
      }
    });
  }

  Future<DeviceMetadata> deviceMetadata() async {
    try {
      final value = await _channel.invokeMapMethod<Object?, Object?>(
        'getDeviceInfo',
      );
      if (value != null) return DeviceMetadata.fromPlatformMap(value);
    } on MissingPluginException {
      // Widget tests and unsupported desktop builds use the Dart fallback.
    }
    return DeviceMetadata(
      platform: Platform.operatingSystem,
      model: 'unknown',
      osVersion: Platform.operatingSystemVersion,
      logicalCpuCores: Platform.numberOfProcessors,
    );
  }

  Future<Map<Object?, Object?>> metricsSnapshot() async {
    try {
      return await _channel.invokeMapMethod<Object?, Object?>(
            'getMetricsSnapshot',
          ) ??
          const {};
    } on MissingPluginException {
      return {
        'memoryBytes': ProcessInfo.currentRss,
        'logicalCpuCores': Platform.numberOfProcessors,
      };
    }
  }

  Future<void> startBackgroundExecution({
    required String runId,
    required String modelName,
  }) async {
    try {
      await _channel.invokeMethod<void>('startBackgroundExecution', {
        'runId': runId,
        'title': 'EdgeSTT 벤치마크 실행 중',
        'subtitle': modelName,
      });
    } on MissingPluginException {
      // Desktop/test fallback does not need a background assertion.
    }
  }

  Future<void> updateBackgroundExecution({
    required int progress,
    required String subtitle,
  }) async {
    try {
      await _channel.invokeMethod<void>('updateBackgroundExecution', {
        'progress': progress,
        'subtitle': subtitle,
      });
    } on MissingPluginException {
      // No-op outside mobile hosts.
    }
  }

  Future<void> finishBackgroundExecution({required bool success}) async {
    try {
      await _channel.invokeMethod<void>('finishBackgroundExecution', {
        'success': success,
      });
    } on MissingPluginException {
      // No-op outside mobile hosts.
    }
  }

  Future<String?> exportResult({
    required String sourcePath,
    required String fileName,
  }) async {
    try {
      return await _channel.invokeMethod<String>('exportResult', {
        'sourcePath': sourcePath,
        'fileName': fileName,
      });
    } on MissingPluginException {
      return null;
    }
  }
}
