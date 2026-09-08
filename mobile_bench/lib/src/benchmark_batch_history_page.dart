import 'package:flutter/material.dart';

import 'benchmark_batch.dart';
import 'benchmark_batch_page.dart';
import 'benchmark_coordinator.dart';
import 'benchmark_services.dart';
import 'result_repository.dart';

class BenchmarkBatchHistoryPage extends StatefulWidget {
  const BenchmarkBatchHistoryPage({
    required this.coordinator,
    required this.samples,
    required this.downloadedModels,
    super.key,
  });

  final BenchmarkCoordinator coordinator;
  final List<AudioSample> samples;
  final List<DownloadedModel> downloadedModels;

  @override
  State<BenchmarkBatchHistoryPage> createState() =>
      _BenchmarkBatchHistoryPageState();
}

class _BenchmarkBatchHistoryPageState
    extends State<BenchmarkBatchHistoryPage> {
  List<BenchmarkBatch>? _batches;

  ResultRepository get _repository => widget.coordinator.results;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final batches = await _repository.listBatches();
    if (mounted) setState(() => _batches = batches);
  }

  Future<void> _delete(BenchmarkBatch batch) async {
    await _repository.deleteBatch(batch.batchId);
    await _load();
  }

  Future<void> _open(BenchmarkBatch batch) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BenchmarkBatchPage(
          coordinator: widget.coordinator,
          samples: widget.samples,
          downloadedModels: widget.downloadedModels,
          existingBatch: batch,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('자동 벤치마크 이력')),
      body: switch (_batches) {
        null => const Center(child: CircularProgressIndicator()),
        [] => const Center(child: Text('저장된 자동 벤치마크 결과가 없습니다.')),
        final batches => ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          itemCount: batches.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (context, index) {
            final batch = batches[index];
            return Card.outlined(
              margin: EdgeInsets.zero,
              child: ListTile(
                leading: Icon(_statusIcon(batch.status)),
                title: Text(_modelName(batch.modelId)),
                subtitle: Text(
                  '${batch.completedCount}/${batch.totalCount} 완료'
                  '${batch.failedCount > 0 ? ' · 실패 ${batch.failedCount}' : ''}'
                  '\n${_formatDate(batch.startedAt)} · ${_statusLabel(batch.status)}',
                ),
                isThreeLine: true,
                onTap: () => _open(batch),
                trailing: IconButton(
                  tooltip: '삭제',
                  onPressed: () => _delete(batch),
                  icon: const Icon(Icons.delete_outline),
                ),
              ),
            );
          },
        ),
      },
    );
  }
}

String _modelName(String modelId) =>
    modelCatalog
        .where((model) => model.id == modelId)
        .map((model) => model.name)
        .firstOrNull ??
    modelId;

String _formatDate(DateTime value) {
  final local = value.toLocal();
  String two(int number) => number.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} '
      '${two(local.hour)}:${two(local.minute)}';
}

String _statusLabel(BenchmarkBatchStatus status) => switch (status) {
  BenchmarkBatchStatus.running => '실행 중',
  BenchmarkBatchStatus.completed => '완료',
  BenchmarkBatchStatus.completedWithErrors => '일부 실패',
  BenchmarkBatchStatus.cancelled => '취소됨',
};

IconData _statusIcon(BenchmarkBatchStatus status) => switch (status) {
  BenchmarkBatchStatus.completed => Icons.check_circle_outline,
  BenchmarkBatchStatus.running => Icons.hourglass_top,
  BenchmarkBatchStatus.cancelled => Icons.cancel_outlined,
  BenchmarkBatchStatus.completedWithErrors => Icons.error_outline,
};
