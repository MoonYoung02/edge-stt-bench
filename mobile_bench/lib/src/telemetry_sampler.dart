import 'dart:async';

import 'benchmark_run.dart';
import 'platform_bridge.dart';

class TelemetrySampler {
  TelemetrySampler({
    required this._platform,
    required this._progress,
    required this._phase,
    required this._appLifecycle,
    required this._onSample,
    this.interval = const Duration(milliseconds: 500),
  });

  final PlatformBridge _platform;
  final int Function() _progress;
  final BenchmarkPhase Function() _phase;
  final String Function() _appLifecycle;
  final void Function(TelemetrySample sample) _onSample;
  final Duration interval;
  final Stopwatch _stopwatch = Stopwatch();
  final List<TelemetrySample> _samples = [];

  Timer? _timer;
  bool _collecting = false;
  double? _previousCpuTimeMs;
  int? _previousElapsedMs;
  double? _lastMemoryMb;
  double? _lastNativeHeapMb;

  List<TelemetrySample> get samples => List.unmodifiable(_samples);
  TelemetrySample? get latest => _samples.lastOrNull;

  Future<void> start() async {
    _stopwatch.start();
    await _collect();
    _timer = Timer.periodic(interval, (_) => _collect());
  }

  Future<List<TelemetrySample>> stop() async {
    _timer?.cancel();
    _timer = null;
    await _collect();
    _stopwatch.stop();
    return samples;
  }

  Future<void> _collect() async {
    if (_collecting) return;
    _collecting = true;
    try {
      final raw = await _platform.metricsSnapshot();
      final elapsedMs = _stopwatch.elapsedMilliseconds;
      final cores =
          (raw['logicalCpuCores'] as num?)?.toInt().clamp(1, 1024) ?? 1;
      final cpuTimeMs = (raw['processCpuTimeMs'] as num?)?.toDouble();
      double? cpuCorePercent;
      if (cpuTimeMs != null &&
          _previousCpuTimeMs != null &&
          _previousElapsedMs != null &&
          elapsedMs - _previousElapsedMs! >= 100) {
        final measuredPercent =
            (cpuTimeMs - _previousCpuTimeMs!) /
            (elapsedMs - _previousElapsedMs!) *
            100;
        if (measuredPercent >= 0) {
          cpuCorePercent = measuredPercent.clamp(0, cores * 100.0).toDouble();
        }
      }
      if (cpuTimeMs != null) {
        _previousCpuTimeMs = cpuTimeMs;
        _previousElapsedMs = elapsedMs;
      }

      final memoryBytes = (raw['memoryBytes'] as num?)?.toDouble();
      final nativeHeapBytes = (raw['nativeHeapBytes'] as num?)?.toDouble();
      if (memoryBytes != null) _lastMemoryMb = memoryBytes / 1000 / 1000;
      if (nativeHeapBytes != null) {
        _lastNativeHeapMb = nativeHeapBytes / 1000 / 1000;
      }
      final sample = TelemetrySample(
        elapsedMs: elapsedMs,
        phase: _phase(),
        progress: _progress().clamp(0, 100) / 100,
        appLifecycle: _appLifecycle(),
        cpuCoreEquivalentPercent: cpuCorePercent,
        cpuDeviceNormalizedPercent: cpuCorePercent == null
            ? null
            : (cpuCorePercent / cores).clamp(0, 100),
        memoryMb: _lastMemoryMb,
        nativeHeapMb: _lastNativeHeapMb,
        thermalStatus: raw['thermalStatus'] as String?,
        thermalHeadroom: _finiteDouble(raw['thermalHeadroom']),
        batteryTemperatureC: _finiteDouble(raw['batteryTemperatureC']),
        batteryLevelPercent: _finiteDouble(raw['batteryLevelPercent']),
        screenInteractive: raw['screenInteractive'] as bool?,
        charging: raw['charging'] as bool?,
      );
      _samples.add(sample);
      _onSample(sample);
    } finally {
      _collecting = false;
    }
  }
}

double? _finiteDouble(Object? value) {
  final number = (value as num?)?.toDouble();
  return number != null && number.isFinite ? number : null;
}
