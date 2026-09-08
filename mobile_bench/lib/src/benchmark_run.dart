import 'dart:io';

import 'benchmark_services.dart';

const int benchmarkSchemaVersion = 1;

enum BenchmarkRunStatus { running, completed, failed, cancelled, interrupted }

enum BenchmarkPhase { preparing, inference, finalizing }

/// Android `thermalStatus` values ordered from coolest to hottest, mirroring
/// `android.os.PowerManager` thermal status constants. Shared by telemetry
/// summarization and the batch runner's thermal guard.
const List<String> thermalStatusOrder = [
  'none',
  'nominal',
  'light',
  'fair',
  'moderate',
  'serious',
  'severe',
  'critical',
  'emergency',
  'shutdown',
];

/// Returns the severity rank of a thermal status string, or -1 if unknown.
/// Higher is hotter.
int thermalSeverityIndex(String? status) {
  if (status == null) return -1;
  return thermalStatusOrder.indexOf(status.toLowerCase());
}

class DeviceMetadata {
  const DeviceMetadata({
    required this.platform,
    required this.model,
    required this.osVersion,
    required this.logicalCpuCores,
    this.manufacturer,
    this.totalMemoryBytes,
  });

  factory DeviceMetadata.fromPlatformMap(Map<Object?, Object?> map) {
    return DeviceMetadata(
      platform: map['platform'] as String? ?? Platform.operatingSystem,
      manufacturer: map['manufacturer'] as String?,
      model: map['model'] as String? ?? 'unknown',
      osVersion: map['osVersion'] as String? ?? Platform.operatingSystemVersion,
      logicalCpuCores:
          (map['logicalCpuCores'] as num?)?.toInt() ??
          Platform.numberOfProcessors,
      totalMemoryBytes: (map['totalMemoryBytes'] as num?)?.toInt(),
    );
  }

  factory DeviceMetadata.fromJson(Map<String, dynamic> json) {
    return DeviceMetadata(
      platform: json['platform'] as String? ?? 'unknown',
      manufacturer: json['manufacturer'] as String?,
      model: json['model'] as String? ?? 'unknown',
      osVersion: json['osVersion'] as String? ?? 'unknown',
      logicalCpuCores: (json['logicalCpuCores'] as num?)?.toInt() ?? 1,
      totalMemoryBytes: (json['totalMemoryBytes'] as num?)?.toInt(),
    );
  }

  final String platform;
  final String? manufacturer;
  final String model;
  final String osVersion;
  final int logicalCpuCores;
  final int? totalMemoryBytes;

  Map<String, dynamic> toJson() => {
    'platform': platform,
    if (manufacturer != null) 'manufacturer': manufacturer,
    'model': model,
    'osVersion': osVersion,
    'logicalCpuCores': logicalCpuCores,
    if (totalMemoryBytes != null) 'totalMemoryBytes': totalMemoryBytes,
  };
}

class TelemetrySample {
  const TelemetrySample({
    required this.elapsedMs,
    required this.phase,
    required this.progress,
    required this.appLifecycle,
    this.cpuCoreEquivalentPercent,
    this.cpuDeviceNormalizedPercent,
    this.memoryMb,
    this.nativeHeapMb,
    this.thermalStatus,
    this.thermalHeadroom,
    this.batteryTemperatureC,
    this.batteryLevelPercent,
    this.screenInteractive,
    this.charging,
  });

  factory TelemetrySample.fromJson(Map<String, dynamic> json) {
    return TelemetrySample(
      elapsedMs: (json['elapsedMs'] as num?)?.toInt() ?? 0,
      phase: BenchmarkPhase.values.byName(
        json['phase'] as String? ?? BenchmarkPhase.preparing.name,
      ),
      progress: (json['progress'] as num?)?.toDouble() ?? 0,
      appLifecycle: json['appLifecycle'] as String? ?? 'unknown',
      cpuCoreEquivalentPercent: (json['cpuCoreEquivalentPercent'] as num?)
          ?.toDouble(),
      cpuDeviceNormalizedPercent: (json['cpuDeviceNormalizedPercent'] as num?)
          ?.toDouble(),
      memoryMb: (json['memoryMb'] as num?)?.toDouble(),
      nativeHeapMb: (json['nativeHeapMb'] as num?)?.toDouble(),
      thermalStatus: json['thermalStatus'] as String?,
      thermalHeadroom: (json['thermalHeadroom'] as num?)?.toDouble(),
      batteryTemperatureC: (json['batteryTemperatureC'] as num?)?.toDouble(),
      batteryLevelPercent: (json['batteryLevelPercent'] as num?)?.toDouble(),
      screenInteractive: json['screenInteractive'] as bool?,
      charging: json['charging'] as bool?,
    );
  }

  final int elapsedMs;
  final BenchmarkPhase phase;
  final double progress;
  final String appLifecycle;
  final double? cpuCoreEquivalentPercent;
  final double? cpuDeviceNormalizedPercent;
  final double? memoryMb;
  final double? nativeHeapMb;
  final String? thermalStatus;
  final double? thermalHeadroom;
  final double? batteryTemperatureC;
  final double? batteryLevelPercent;
  final bool? screenInteractive;
  final bool? charging;

  Map<String, dynamic> toJson() => {
    'elapsedMs': elapsedMs,
    'phase': phase.name,
    'progress': progress,
    'appLifecycle': appLifecycle,
    if (cpuCoreEquivalentPercent != null)
      'cpuCoreEquivalentPercent': cpuCoreEquivalentPercent,
    if (cpuDeviceNormalizedPercent != null)
      'cpuDeviceNormalizedPercent': cpuDeviceNormalizedPercent,
    if (memoryMb != null) 'memoryMb': memoryMb,
    if (nativeHeapMb != null) 'nativeHeapMb': nativeHeapMb,
    if (thermalStatus != null) 'thermalStatus': thermalStatus,
    if (thermalHeadroom != null) 'thermalHeadroom': thermalHeadroom,
    if (batteryTemperatureC != null) 'batteryTemperatureC': batteryTemperatureC,
    if (batteryLevelPercent != null) 'batteryLevelPercent': batteryLevelPercent,
    if (screenInteractive != null) 'screenInteractive': screenInteractive,
    if (charging != null) 'charging': charging,
  };
}

class TelemetrySummary {
  const TelemetrySummary({
    this.averageCpuPercent,
    this.peakCpuPercent,
    this.averageMemoryMb,
    this.peakMemoryMb,
    this.maximumThermalStatus,
    this.maximumThermalHeadroom,
    this.maximumBatteryTemperatureC,
  });

  factory TelemetrySummary.fromSamples(List<TelemetrySample> samples) {
    final cpu = samples
        .map((sample) => sample.cpuCoreEquivalentPercent)
        .whereType<double>()
        .toList();
    final memory = samples
        .map((sample) => sample.memoryMb)
        .whereType<double>()
        .toList();
    final headroom = samples
        .map((sample) => sample.thermalHeadroom)
        .whereType<double>()
        .toList();
    final batteryTemperature = samples
        .map((sample) => sample.batteryTemperatureC)
        .whereType<double>()
        .toList();
    final thermal = samples
        .map((sample) => sample.thermalStatus)
        .whereType<String>()
        .fold<String?>(null, _hotterThermalStatus);
    return TelemetrySummary(
      averageCpuPercent: _average(cpu),
      peakCpuPercent: _maximum(cpu),
      averageMemoryMb: _average(memory),
      peakMemoryMb: _maximum(memory),
      maximumThermalStatus: thermal,
      maximumThermalHeadroom: _maximum(headroom),
      maximumBatteryTemperatureC: _maximum(batteryTemperature),
    );
  }

  factory TelemetrySummary.fromJson(Map<String, dynamic> json) {
    return TelemetrySummary(
      averageCpuPercent: (json['averageCpuPercent'] as num?)?.toDouble(),
      peakCpuPercent: (json['peakCpuPercent'] as num?)?.toDouble(),
      averageMemoryMb: (json['averageMemoryMb'] as num?)?.toDouble(),
      peakMemoryMb: (json['peakMemoryMb'] as num?)?.toDouble(),
      maximumThermalStatus: json['maximumThermalStatus'] as String?,
      maximumThermalHeadroom: (json['maximumThermalHeadroom'] as num?)
          ?.toDouble(),
      maximumBatteryTemperatureC: (json['maximumBatteryTemperatureC'] as num?)
          ?.toDouble(),
    );
  }

  final double? averageCpuPercent;
  final double? peakCpuPercent;
  final double? averageMemoryMb;
  final double? peakMemoryMb;
  final String? maximumThermalStatus;
  final double? maximumThermalHeadroom;
  final double? maximumBatteryTemperatureC;

  Map<String, dynamic> toJson() => {
    if (averageCpuPercent != null) 'averageCpuPercent': averageCpuPercent,
    if (peakCpuPercent != null) 'peakCpuPercent': peakCpuPercent,
    if (averageMemoryMb != null) 'averageMemoryMb': averageMemoryMb,
    if (peakMemoryMb != null) 'peakMemoryMb': peakMemoryMb,
    if (maximumThermalStatus != null)
      'maximumThermalStatus': maximumThermalStatus,
    if (maximumThermalHeadroom != null)
      'maximumThermalHeadroom': maximumThermalHeadroom,
    if (maximumBatteryTemperatureC != null)
      'maximumBatteryTemperatureC': maximumBatteryTemperatureC,
  };
}

class BenchmarkRun {
  BenchmarkRun({
    required this.runId,
    required this.status,
    required this.startedAt,
    required this.sampleAssetPath,
    required this.modelId,
    required this.modelPath,
    required this.threads,
    required this.device,
    this.completedAt,
    this.result,
    this.samples = const [],
    this.error,
    this.cancelRequested = false,
    this.batchId,
    this.sampleId,
  });

  factory BenchmarkRun.fromJson(Map<String, dynamic> json) {
    final resultJson = json['result'] as Map<String, dynamic>?;
    return BenchmarkRun(
      runId: json['runId'] as String,
      status: BenchmarkRunStatus.values.byName(json['status'] as String),
      startedAt: DateTime.parse(json['startedAt'] as String),
      completedAt: json['completedAt'] == null
          ? null
          : DateTime.parse(json['completedAt'] as String),
      sampleAssetPath: json['sampleAssetPath'] as String,
      modelId: json['modelId'] as String,
      modelPath: json['modelPath'] as String? ?? '',
      threads: (json['threads'] as num?)?.toInt() ?? 4,
      device: DeviceMetadata.fromJson(
        Map<String, dynamic>.from(json['device'] as Map),
      ),
      result: resultJson == null
          ? null
          : _resultFromJson(
              resultJson,
              modelId: json['modelId'] as String,
              modelPath: json['modelPath'] as String? ?? '',
              sampleAssetPath: json['sampleAssetPath'] as String,
            ),
      samples: (json['samples'] as List<dynamic>? ?? const [])
          .map(
            (value) => TelemetrySample.fromJson(
              Map<String, dynamic>.from(value as Map),
            ),
          )
          .toList(growable: false),
      error: json['error'] as String?,
      cancelRequested: json['cancelRequested'] as bool? ?? false,
      batchId: json['batchId'] as String?,
      sampleId: json['sampleId'] as String?,
    );
  }

  final String runId;
  BenchmarkRunStatus status;
  final DateTime startedAt;
  DateTime? completedAt;
  final String sampleAssetPath;
  final String modelId;
  final String modelPath;
  final int threads;
  final DeviceMetadata device;
  BenchmarkResult? result;
  List<TelemetrySample> samples;
  String? error;
  bool cancelRequested;
  final String? batchId;
  final String? sampleId;

  TelemetrySummary get summary => TelemetrySummary.fromSamples(samples);

  Map<String, dynamic> toJson() => {
    'schemaVersion': benchmarkSchemaVersion,
    'runId': runId,
    'status': status.name,
    'startedAt': startedAt.toUtc().toIso8601String(),
    if (completedAt != null)
      'completedAt': completedAt!.toUtc().toIso8601String(),
    'sampleAssetPath': sampleAssetPath,
    'modelId': modelId,
    'modelPath': modelPath,
    'threads': threads,
    'device': device.toJson(),
    'summary': summary.toJson(),
    'samples': samples.map((sample) => sample.toJson()).toList(),
    if (result != null) 'result': _resultToJson(result!),
    if (error != null) 'error': error,
    'cancelRequested': cancelRequested,
    if (batchId != null) 'batchId': batchId,
    if (sampleId != null) 'sampleId': sampleId,
  };
}

Map<String, dynamic> _resultToJson(BenchmarkResult result) => {
  'transcript': result.transcript,
  'formattedTranscript': result.formattedTranscript,
  'transcriptSegments': result.transcriptSegments
      .map(
        (segment) => {
          'fromMs': segment.from.inMilliseconds,
          'toMs': segment.to.inMilliseconds,
          'text': segment.text,
        },
      )
      .toList(),
  'stagingTimeMs': result.stagingTime.inMilliseconds,
  'processingTimeMs': result.processingTime.inMilliseconds,
  if (result.audioDuration != null)
    'audioDurationMs': result.audioDuration!.inMilliseconds,
  if (result.reference != null) 'reference': result.reference,
  'segments': result.segments,
};

BenchmarkResult _resultFromJson(
  Map<String, dynamic> json, {
  required String modelId,
  required String modelPath,
  required String sampleAssetPath,
}) {
  final model = modelCatalog.where((value) => value.id == modelId).firstOrNull;
  if (model == null) {
    throw FormatException('알 수 없는 모델 ID입니다: $modelId');
  }
  final transcriptSegments =
      (json['transcriptSegments'] as List<dynamic>? ?? [])
          .map((value) {
            final segment = Map<String, dynamic>.from(value as Map);
            return BenchmarkSegment(
              from: Duration(milliseconds: (segment['fromMs'] as num).toInt()),
              to: Duration(milliseconds: (segment['toMs'] as num).toInt()),
              text: segment['text'] as String? ?? '',
            );
          })
          .toList(growable: false);
  return BenchmarkResult(
    sample: AudioSample(assetPath: sampleAssetPath),
    transcript: json['transcript'] as String? ?? '',
    formattedTranscript: json['formattedTranscript'] as String? ?? '',
    transcriptSegments: transcriptSegments,
    stagingTime: Duration(
      milliseconds: (json['stagingTimeMs'] as num?)?.toInt() ?? 0,
    ),
    processingTime: Duration(
      milliseconds: (json['processingTimeMs'] as num?)?.toInt() ?? 0,
    ),
    audioDuration: json['audioDurationMs'] == null
        ? null
        : Duration(milliseconds: (json['audioDurationMs'] as num).toInt()),
    reference: json['reference'] as String?,
    model: DownloadedModel(spec: model, file: File(modelPath)),
    segments: (json['segments'] as num?)?.toInt() ?? transcriptSegments.length,
  );
}

double? _average(List<double> values) {
  if (values.isEmpty) return null;
  return values.reduce((a, b) => a + b) / values.length;
}

double? _maximum(List<double> values) {
  if (values.isEmpty) return null;
  return values.reduce((a, b) => a > b ? a : b);
}

String? _hotterThermalStatus(String? current, String next) {
  if (current == null) return next;
  return thermalSeverityIndex(next) > thermalSeverityIndex(current)
      ? next
      : current;
}
