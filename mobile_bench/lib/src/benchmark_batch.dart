/// Groups a sequence of single-sample [BenchmarkRun]s (one per dataset
/// sample) that were executed back-to-back for the same model/thread
/// configuration, so a labeled dataset (e.g. all 22 KCSC files) can be
/// benchmarked automatically instead of one sample at a time.
///
/// Accuracy (CER/WER) is intentionally not computed on-device: each
/// completed run already carries `result.transcript` and `result.reference`,
/// and the existing desktop `sttbench` evaluator scores those once the batch
/// is exported (see `mobile_bench/tools/mobile_result_importer.py`). This
/// keeps the CER/WER implementation in one place instead of duplicating it
/// in Dart.
library;

const int benchmarkBatchSchemaVersion = 1;

enum BenchmarkBatchStatus { running, completed, completedWithErrors, cancelled }

enum BenchmarkBatchEntryStatus { pending, running, completed, failed, skipped }

class BenchmarkBatchEntry {
  BenchmarkBatchEntry({
    required this.sampleId,
    required this.sampleAssetPath,
    this.status = BenchmarkBatchEntryStatus.pending,
    this.runId,
    this.error,
    this.thermalStatusAtStart,
    this.thermalThrottled = false,
    this.reusedFromPriorRun = false,
  });

  factory BenchmarkBatchEntry.fromJson(Map<String, dynamic> json) {
    return BenchmarkBatchEntry(
      sampleId: json['sampleId'] as String,
      sampleAssetPath: json['sampleAssetPath'] as String,
      status: BenchmarkBatchEntryStatus.values.byName(
        json['status'] as String? ?? BenchmarkBatchEntryStatus.pending.name,
      ),
      runId: json['runId'] as String?,
      error: json['error'] as String?,
      thermalStatusAtStart: json['thermalStatusAtStart'] as String?,
      thermalThrottled: json['thermalThrottled'] as bool? ?? false,
      reusedFromPriorRun: json['reusedFromPriorRun'] as bool? ?? false,
    );
  }

  final String sampleId;
  final String sampleAssetPath;
  BenchmarkBatchEntryStatus status;
  String? runId;
  String? error;
  String? thermalStatusAtStart;
  bool thermalThrottled;

  /// True when this entry was never executed by this batch because a prior
  /// run (manual or from an earlier batch) already completed the same
  /// model+sample combination — [runId] then points at that earlier run
  /// instead of one this batch produced. See
  /// `BenchmarkCoordinator.runBatch`.
  bool reusedFromPriorRun;

  Map<String, dynamic> toJson() => {
    'sampleId': sampleId,
    'sampleAssetPath': sampleAssetPath,
    'status': status.name,
    if (runId != null) 'runId': runId,
    if (error != null) 'error': error,
    if (thermalStatusAtStart != null)
      'thermalStatusAtStart': thermalStatusAtStart,
    'thermalThrottled': thermalThrottled,
    'reusedFromPriorRun': reusedFromPriorRun,
  };
}

class BenchmarkBatch {
  BenchmarkBatch({
    required this.batchId,
    required this.modelId,
    required this.threads,
    required this.startedAt,
    required this.entries,
    this.status = BenchmarkBatchStatus.running,
    this.completedAt,
    this.cancelRequested = false,
  });

  factory BenchmarkBatch.fromJson(Map<String, dynamic> json) {
    return BenchmarkBatch(
      batchId: json['batchId'] as String,
      modelId: json['modelId'] as String,
      threads: (json['threads'] as num?)?.toInt() ?? 4,
      startedAt: DateTime.parse(json['startedAt'] as String),
      completedAt: json['completedAt'] == null
          ? null
          : DateTime.parse(json['completedAt'] as String),
      status: BenchmarkBatchStatus.values.byName(
        json['status'] as String? ?? BenchmarkBatchStatus.running.name,
      ),
      cancelRequested: json['cancelRequested'] as bool? ?? false,
      entries: (json['entries'] as List<dynamic>? ?? const [])
          .map(
            (value) => BenchmarkBatchEntry.fromJson(
              Map<String, dynamic>.from(value as Map),
            ),
          )
          .toList(),
    );
  }

  final String batchId;
  final String modelId;
  final int threads;
  final DateTime startedAt;
  DateTime? completedAt;
  BenchmarkBatchStatus status;
  bool cancelRequested;
  final List<BenchmarkBatchEntry> entries;

  int get completedCount =>
      entries.where((e) => e.status == BenchmarkBatchEntryStatus.completed).length;
  int get failedCount =>
      entries.where((e) => e.status == BenchmarkBatchEntryStatus.failed).length;
  int get totalCount => entries.length;
  bool get isFinished => status != BenchmarkBatchStatus.running;

  Map<String, dynamic> toJson() => {
    'schemaVersion': benchmarkBatchSchemaVersion,
    'batchId': batchId,
    'modelId': modelId,
    'threads': threads,
    'startedAt': startedAt.toUtc().toIso8601String(),
    if (completedAt != null)
      'completedAt': completedAt!.toUtc().toIso8601String(),
    'status': status.name,
    'cancelRequested': cancelRequested,
    'entries': entries.map((entry) => entry.toJson()).toList(),
  };
}
