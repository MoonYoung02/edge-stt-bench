import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'benchmark_batch.dart';
import 'benchmark_run.dart';

typedef ResultDirectoryProvider = Future<Directory> Function();

class ResultRepository {
  ResultRepository({ResultDirectoryProvider? directoryProvider})
    : _directoryProvider = directoryProvider ?? _defaultDirectory;

  final ResultDirectoryProvider _directoryProvider;

  static Future<Directory> _defaultDirectory() async {
    final support = await getApplicationSupportDirectory();
    return Directory('${support.path}/results');
  }

  Future<Directory> directory() async {
    final result = await _directoryProvider();
    await result.create(recursive: true);
    return result;
  }

  Future<File> fileFor(String runId) async {
    final root = await directory();
    return File('${root.path}/$runId.json');
  }

  Future<File> save(BenchmarkRun run) async {
    final target = await fileFor(run.runId);
    final temporary = File('${target.path}.tmp');
    final encoder = const JsonEncoder.withIndent('  ');
    await temporary.writeAsString(encoder.convert(run.toJson()), flush: true);
    if (await target.exists()) await target.delete();
    return temporary.rename(target.path);
  }

  Future<BenchmarkRun?> get(String runId) async {
    final file = await fileFor(runId);
    if (!await file.exists()) return null;
    try {
      final json = jsonDecode(await file.readAsString());
      return BenchmarkRun.fromJson(Map<String, dynamic>.from(json as Map));
    } on Object {
      return null;
    }
  }

  Future<List<BenchmarkRun>> list() async {
    final root = await directory();
    final runs = <BenchmarkRun>[];
    await for (final entity in root.list()) {
      if (entity is! File || !entity.path.endsWith('.json')) continue;
      try {
        final json = jsonDecode(await entity.readAsString());
        runs.add(BenchmarkRun.fromJson(Map<String, dynamic>.from(json as Map)));
      } on Object {
        // A damaged or newer-schema result must not hide all other history.
      }
    }
    runs.sort((a, b) => b.startedAt.compareTo(a.startedAt));
    return runs;
  }

  Future<void> markInterruptedRuns() async {
    for (final run in await list()) {
      if (run.status != BenchmarkRunStatus.running) continue;
      run
        ..status = BenchmarkRunStatus.interrupted
        ..completedAt = DateTime.now()
        ..error = '앱 프로세스가 종료되어 벤치마크가 중단되었습니다.';
      await save(run);
    }
  }

  Future<void> delete(String runId) async {
    final file = await fileFor(runId);
    if (await file.exists()) await file.delete();
  }

  /// Runs that belong to the given batch, in the order they were saved.
  Future<List<BenchmarkRun>> listForBatch(String batchId) async {
    final runs = await list();
    return runs.where((run) => run.batchId == batchId).toList();
  }

  Future<Directory> _batchDirectory() async {
    final root = await directory();
    final batches = Directory('${root.path}/batches');
    await batches.create(recursive: true);
    return batches;
  }

  Future<File> batchFileFor(String batchId) async {
    final root = await _batchDirectory();
    return File('${root.path}/$batchId.json');
  }

  Future<File> saveBatch(BenchmarkBatch batch) async {
    final target = await batchFileFor(batch.batchId);
    final temporary = File('${target.path}.tmp');
    final encoder = const JsonEncoder.withIndent('  ');
    await temporary.writeAsString(
      encoder.convert(batch.toJson()),
      flush: true,
    );
    if (await target.exists()) await target.delete();
    return temporary.rename(target.path);
  }

  Future<List<BenchmarkBatch>> listBatches() async {
    final root = await _batchDirectory();
    final batches = <BenchmarkBatch>[];
    await for (final entity in root.list()) {
      if (entity is! File || !entity.path.endsWith('.json')) continue;
      try {
        final json = jsonDecode(await entity.readAsString());
        batches.add(
          BenchmarkBatch.fromJson(Map<String, dynamic>.from(json as Map)),
        );
      } on Object {
        // A damaged or newer-schema batch record must not hide the rest.
      }
    }
    batches.sort((a, b) => b.startedAt.compareTo(a.startedAt));
    return batches;
  }

  Future<void> markInterruptedBatches() async {
    for (final batch in await listBatches()) {
      if (batch.status != BenchmarkBatchStatus.running) continue;
      for (final entry in batch.entries) {
        if (entry.status == BenchmarkBatchEntryStatus.running ||
            entry.status == BenchmarkBatchEntryStatus.pending) {
          entry.status = BenchmarkBatchEntryStatus.skipped;
          entry.error ??= '앱 프로세스가 종료되어 실행되지 못했습니다.';
        }
      }
      batch
        ..status = BenchmarkBatchStatus.completedWithErrors
        ..completedAt = DateTime.now();
      await saveBatch(batch);
    }
  }

  Future<void> deleteBatch(String batchId, {bool deleteRuns = false}) async {
    if (deleteRuns) {
      for (final run in await listForBatch(batchId)) {
        await delete(run.runId);
      }
    }
    final file = await batchFileFor(batchId);
    if (await file.exists()) await file.delete();
  }
}
