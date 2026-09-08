import 'dart:async';
import 'dart:math';

import 'package:flutter/widgets.dart';
import 'package:wakelock_plus/wakelock_plus.dart';
import 'package:whisper_ggml/whisper_ggml.dart';

import 'benchmark_batch.dart';
import 'benchmark_run.dart';
import 'benchmark_services.dart';
import 'platform_bridge.dart';
import 'result_repository.dart';
import 'sherpa_engine.dart';
import 'telemetry_sampler.dart';

/// Thermal statuses at or above this severity get an entry's
/// `thermalThrottled` flag set (see [BenchmarkCoordinator._recordThermalState])
/// so a hot measurement can be spotted later — the batch itself never pauses
/// for it.
const int _batchThermalPauseThreshold = 5; // 'serious' in [thermalStatusOrder]

class BenchmarkCoordinator extends ChangeNotifier with WidgetsBindingObserver {
  BenchmarkCoordinator({
    ResultRepository? results,
    PlatformBridge? platform,
    WhisperBenchmarkEngine? whisperEngine,
    SherpaOnnxEngine? sherpaEngine,
  }) : results = results ?? ResultRepository(),
       platform = platform ?? PlatformBridge(),
       _whisperEngine = whisperEngine ?? WhisperBenchmarkEngine(),
       _sherpaEngine = sherpaEngine ?? SherpaOnnxEngine();

  final ResultRepository results;
  final PlatformBridge platform;
  final WhisperBenchmarkEngine _whisperEngine;
  final SherpaOnnxEngine _sherpaEngine;

  /// whisper.cpp and sherpa-onnx models are two separate native runtimes;
  /// [ModelSpec.engine] says which one a given [DownloadedModel] needs.
  SttBenchmarkEngine _engineFor(ModelSpec spec) =>
      spec.engine == SttEngineKind.whisperCpp ? _whisperEngine : _sherpaEngine;

  BenchmarkRun? _activeRun;
  BenchmarkRun? _latestRun;
  TelemetrySampler? _sampler;
  BenchmarkPhase _phase = BenchmarkPhase.preparing;
  String _appLifecycle = 'resumed';
  int _progress = 0;
  String _status = '준비됨';
  String? _error;
  bool _initialized = false;
  bool _cancelRequested = false;
  int _lastNotificationProgress = -1;
  Timer? _checkpointTimer;
  Future<void> _checkpointTail = Future.value();

  BenchmarkBatch? _activeBatch;
  bool _batchCancelRequested = false;

  /// Reference count for the screen wakelock: [runBatch] acquires it once
  /// for the whole batch and each per-sample [run] call also acquires/
  /// releases it, so the screen stays on continuously across every sample
  /// instead of flickering to sleep between them. See [_acquireWakelock].
  int _wakelockRefCount = 0;

  BenchmarkRun? get activeRun => _activeRun;
  BenchmarkRun? get latestRun => _latestRun;
  BenchmarkBatch? get activeBatch => _activeBatch;
  TelemetrySample? get latestTelemetry => _sampler?.latest;
  List<TelemetrySample> get liveSamples => _sampler?.samples ?? const [];
  bool get isRunning => _activeRun?.status == BenchmarkRunStatus.running;
  bool get isRunningBatch => _activeBatch != null;
  bool get isBusy => isRunning || isRunningBatch;
  bool get initialized => _initialized;
  double? get progress => isRunning ? _progress / 100 : null;
  String get status => _status;
  String? get error => _error;

  Future<void> initialize() async {
    if (_initialized) return;
    platform
      ..initialize()
      ..onCancelRequested = requestCancel
      ..onExecutionExpired = requestCancel;
    WidgetsBinding.instance.addObserver(this);
    await results.markInterruptedRuns();
    await results.markInterruptedBatches();
    final history = await results.list();
    _latestRun = history.where((run) => run.result != null).firstOrNull;
    _initialized = true;
    notifyListeners();
  }

  Future<BenchmarkRun?> run({
    required AudioSample sample,
    required DownloadedModel model,
    required int threads,
    String? batchId,
    String? sampleId,
  }) async {
    if (isRunning) return null;
    _progress = 0;
    _phase = BenchmarkPhase.preparing;
    _status = '오디오 준비 중';
    _error = null;
    _cancelRequested = false;
    _lastNotificationProgress = -1;

    final run = BenchmarkRun(
      runId: _newRunId(label: model.spec.id),
      status: BenchmarkRunStatus.running,
      startedAt: DateTime.now(),
      sampleAssetPath: sample.assetPath,
      modelId: model.spec.id,
      modelPath: model.file.path,
      threads: threads,
      device: await platform.deviceMetadata(),
      batchId: batchId,
      sampleId: sampleId,
    );
    _activeRun = run;
    await results.save(run);
    notifyListeners();
    await _acquireWakelock();

    try {
      await platform.startBackgroundExecution(
        runId: run.runId,
        modelName: model.spec.name,
      );
      _sampler = TelemetrySampler(
        platform: platform,
        progress: () => _progress,
        phase: () => _phase,
        appLifecycle: () => _appLifecycle,
        onSample: (_) => notifyListeners(),
      );
      await _sampler!.start();
      _checkpointTimer = Timer.periodic(
        const Duration(seconds: 5),
        (_) => _queueCheckpoint(run),
      );

      final result = await _engineFor(model.spec).run(
        sample: sample,
        model: model,
        threads: threads,
        onInferenceStarted: () {
          _phase = BenchmarkPhase.inference;
          _status = 'STT 실행 중 · 0%';
          notifyListeners();
        },
        onProgress: (value) {
          _progress = value.clamp(0, 100);
          _status = 'STT 실행 중 · $_progress%';
          notifyListeners();
          if ((_progress - _lastNotificationProgress).abs() >= 2) {
            _lastNotificationProgress = _progress;
            platform.updateBackgroundExecution(
              progress: _progress,
              subtitle: '${model.spec.name} · $_progress%',
            );
          }
        },
      );
      _phase = BenchmarkPhase.finalizing;
      _checkpointTimer?.cancel();
      await _checkpointTail;
      run.samples = await _sampler!.stop();
      run
        ..result = result
        ..status = _cancelRequested
            ? BenchmarkRunStatus.cancelled
            : BenchmarkRunStatus.completed
        ..cancelRequested = _cancelRequested
        ..completedAt = DateTime.now();
      _status = _cancelRequested ? '벤치마크 취소됨' : '벤치마크 완료';
      _progress = _cancelRequested ? _progress : 100;
      await results.save(run);
      _latestRun = run;
      return run;
    } catch (exception) {
      _checkpointTimer?.cancel();
      await _checkpointTail;
      run.samples = await _sampler?.stop() ?? const [];
      run
        ..status = _cancelRequested
            ? BenchmarkRunStatus.cancelled
            : BenchmarkRunStatus.failed
        ..cancelRequested = _cancelRequested
        ..completedAt = DateTime.now()
        ..error = exception.toString();
      _error = run.error;
      _status = _cancelRequested ? '벤치마크 취소됨' : '실행 실패';
      await results.save(run);
      rethrow;
    } finally {
      _checkpointTimer?.cancel();
      _checkpointTimer = null;
      await platform.finishBackgroundExecution(
        success: run.status == BenchmarkRunStatus.completed,
      );
      _activeRun = null;
      _sampler = null;
      await _releaseWakelock();
      notifyListeners();
    }
  }

  /// Runs [model] against every sample in [samples] that has a reference
  /// transcript, one at a time, reusing [run] for each. Samples without a
  /// `referenceAssetPath` are skipped up front: CER/WER cannot be scored for
  /// them (see docs/DATASET.md §7).
  ///
  /// Before starting, checks history for a sample already benchmarked with
  /// this exact model (any past run, not just an earlier batch) and skips
  /// re-running those — the entry is marked completed right away, pointing
  /// at the prior run instead (`entry.reusedFromPriorRun`). This makes it
  /// cheap to top up a batch after adding new samples, or to resume one that
  /// only got partway through model+dataset coverage before being cancelled
  /// or interrupted.
  ///
  /// Each sample's [BenchmarkRun] is tagged with the returned batch's
  /// `batchId` and persisted individually, exactly like a manual run, so the
  /// existing history/export/upload flows keep working unchanged. The batch
  /// record itself only tracks per-sample status for the progress UI and for
  /// grouping results on the desktop import side.
  Future<BenchmarkBatch> runBatch({
    required List<AudioSample> samples,
    required DownloadedModel model,
    required int threads,
  }) async {
    if (isBusy) throw StateError('이미 실행 중입니다.');
    final labeled = samples
        .where((sample) => sample.referenceAssetPath != null)
        .toList(growable: false);
    if (labeled.isEmpty) {
      throw StateError('정답 텍스트가 있는 샘플이 없습니다.');
    }

    await _acquireWakelock();
    try {
      final priorRunIds = await results.completedRunIdsBySample(
        modelId: model.spec.id,
      );

      final batch = BenchmarkBatch(
        batchId: _newRunId(label: model.spec.id),
        modelId: model.spec.id,
        threads: threads,
        startedAt: DateTime.now(),
        entries: labeled.map((sample) {
          final priorRunId = priorRunIds[sample.assetPath];
          return BenchmarkBatchEntry(
            sampleId: sample.fileName,
            sampleAssetPath: sample.assetPath,
            status: priorRunId == null
                ? BenchmarkBatchEntryStatus.pending
                : BenchmarkBatchEntryStatus.completed,
            runId: priorRunId,
            reusedFromPriorRun: priorRunId != null,
          );
        }).toList(),
      );
      _activeBatch = batch;
      _batchCancelRequested = false;
      await results.saveBatch(batch);
      notifyListeners();

      for (var index = 0; index < labeled.length; index++) {
        final entry = batch.entries[index];
        if (entry.reusedFromPriorRun) continue;
        if (_batchCancelRequested) {
          entry.status = BenchmarkBatchEntryStatus.skipped;
          await results.saveBatch(batch);
          continue;
        }

        await _recordThermalState(entry);

        entry.status = BenchmarkBatchEntryStatus.running;
        await results.saveBatch(batch);
        notifyListeners();

        try {
          final sampleRun = await run(
            sample: labeled[index],
            model: model,
            threads: threads,
            batchId: batch.batchId,
            sampleId: entry.sampleId,
          );
          entry.runId = sampleRun?.runId;
          if (sampleRun?.status == BenchmarkRunStatus.cancelled) {
            _batchCancelRequested = true;
            entry.status = BenchmarkBatchEntryStatus.skipped;
          } else {
            entry.status = sampleRun?.status == BenchmarkRunStatus.completed
                ? BenchmarkBatchEntryStatus.completed
                : BenchmarkBatchEntryStatus.failed;
          }
        } catch (exception) {
          if (_cancelRequested) {
            _batchCancelRequested = true;
            entry.status = BenchmarkBatchEntryStatus.skipped;
          } else {
            entry.status = BenchmarkBatchEntryStatus.failed;
            entry.error = exception.toString();
          }
        }
        await results.saveBatch(batch);
        notifyListeners();
      }

      batch
        ..status = _batchCancelRequested
            ? BenchmarkBatchStatus.cancelled
            : (batch.failedCount > 0
                  ? BenchmarkBatchStatus.completedWithErrors
                  : BenchmarkBatchStatus.completed)
        ..cancelRequested = _batchCancelRequested
        ..completedAt = DateTime.now();
      await results.saveBatch(batch);
      _activeBatch = null;
      _status = '준비됨';
      notifyListeners();
      return batch;
    } finally {
      await _releaseWakelock();
    }
  }

  Future<void> requestCancelBatch() async {
    if (!isRunningBatch) return;
    _batchCancelRequested = true;
    _activeBatch?.cancelRequested = true;
    notifyListeners();
    if (isRunning) await requestCancel();
  }

  /// Records the device thermal status right before a batch sample starts,
  /// without pausing for it — a batch that keeps stopping to wait out heat
  /// is worse than one that finishes with a few samples flagged as measured
  /// hot. `entry.thermalThrottled` still lets the desktop importer exclude
  /// or call out a throttled sample's RTF instead of trusting it blindly.
  Future<void> _recordThermalState(BenchmarkBatchEntry entry) async {
    final snapshot = await platform.metricsSnapshot();
    final status = snapshot['thermalStatus'] as String?;
    entry.thermalStatusAtStart = status;
    entry.thermalThrottled = thermalSeverityIndex(status) >= _batchThermalPauseThreshold;
  }

  /// Keeps the screen on (no lock screen, no display sleep) for as long as
  /// a benchmark is running — a long KCSC file or a full 22-sample batch
  /// otherwise gets interrupted by the screen locking mid-run, and RTF
  /// comparisons are more trustworthy when every run measures under the
  /// same screen-on state instead of some samples happening to run through
  /// a lock. Ref-counted so a batch's outer acquire and each inner [run]'s
  /// own acquire/release don't turn the wakelock off between samples.
  Future<void> _acquireWakelock() async {
    _wakelockRefCount++;
    if (_wakelockRefCount > 1) return;
    try {
      await WakelockPlus.enable();
    } on Object {
      // Desktop/test hosts and platforms without the plugin's native side
      // must not abort the benchmark over a screen-on nicety.
    }
  }

  Future<void> _releaseWakelock() async {
    if (_wakelockRefCount == 0) return;
    _wakelockRefCount--;
    if (_wakelockRefCount > 0) return;
    try {
      await WakelockPlus.disable();
    } on Object {
      // See _acquireWakelock.
    }
  }

  Future<void> requestCancel() async {
    if (!isRunning || _cancelRequested) return;
    _cancelRequested = true;
    _activeRun?.cancelRequested = true;
    _status = '취소 요청 중';
    notifyListeners();
    try {
      await Whisper.cancelCurrentTranscription();
    } on Object {
      // The run state is still marked cancelled; an in-flight FFI call will
      // complete naturally if the current host cannot expose cancellation.
    }
  }

  void _queueCheckpoint(BenchmarkRun run) {
    final snapshot = _sampler?.samples;
    if (snapshot == null) return;
    _checkpointTail = _checkpointTail.then((_) async {
      if (run.status != BenchmarkRunStatus.running) return;
      run.samples = snapshot;
      try {
        await results.save(run);
      } on Object {
        // Final persistence still runs when the benchmark finishes. A single
        // failed periodic checkpoint must not abort native inference.
      }
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appLifecycle = state.name;
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }
}

/// Builds a run/batch id that doubles as its file name (`ResultRepository`
/// names files after it verbatim, and the export button on the result page
/// uses it as-is too). [label] — normally a model id such as
/// `whisper-small-q8_0` — is prefixed so a pulled or exported JSON file
/// shows which model produced it without opening it first.
String _newRunId({String? label}) {
  final now = DateTime.now().toUtc();
  final random = Random.secure()
      .nextInt(0xFFFFFF)
      .toRadixString(16)
      .padLeft(6, '0');
  final timestamp = now.toIso8601String().replaceAll(RegExp('[-:.Z]'), '');
  final prefix = label == null ? '' : '${_sanitizeForFileName(label)}-';
  return '$prefix$timestamp-$random';
}

String _sanitizeForFileName(String value) =>
    value.replaceAll(RegExp(r'[^A-Za-z0-9._-]+'), '-');
