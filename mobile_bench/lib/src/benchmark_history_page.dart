import 'package:flutter/material.dart';

import 'benchmark_result_page.dart';
import 'benchmark_run.dart';
import 'benchmark_services.dart';
import 'result_repository.dart';

class BenchmarkHistoryPage extends StatefulWidget {
  const BenchmarkHistoryPage({required this.repository, super.key});

  final ResultRepository repository;

  @override
  State<BenchmarkHistoryPage> createState() => _BenchmarkHistoryPageState();
}

class _BenchmarkHistoryPageState extends State<BenchmarkHistoryPage> {
  List<BenchmarkRun>? _runs;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final runs = await widget.repository.list();
    if (mounted) setState(() => _runs = runs);
  }

  Future<void> _delete(BenchmarkRun run) async {
    await widget.repository.delete(run.runId);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('결과 이력')),
      body: switch (_runs) {
        null => const Center(child: CircularProgressIndicator()),
        [] => const Center(child: Text('저장된 벤치마크 결과가 없습니다.')),
        final runs => ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          itemCount: runs.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (context, index) {
            final run = runs[index];
            final result = run.result;
            return Card.outlined(
              margin: EdgeInsets.zero,
              child: ListTile(
                leading: Icon(_statusIcon(run.status)),
                title: Text(_modelName(run.modelId)),
                subtitle: Text(
                  '${run.sampleAssetPath.split('/').last}\n'
                  '${_formatDate(run.startedAt)} · ${_statusLabel(run.status)}',
                ),
                isThreeLine: true,
                onTap: result == null
                    ? null
                    : () => Navigator.of(context).push<void>(
                        MaterialPageRoute(
                          builder: (_) => BenchmarkResultPage(
                            result: result,
                            run: run,
                            repository: widget.repository,
                          ),
                        ),
                      ),
                trailing: IconButton(
                  tooltip: '삭제',
                  onPressed: () => _delete(run),
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

String _statusLabel(BenchmarkRunStatus status) => switch (status) {
  BenchmarkRunStatus.running => '실행 중',
  BenchmarkRunStatus.completed => '완료',
  BenchmarkRunStatus.failed => '실패',
  BenchmarkRunStatus.cancelled => '취소됨',
  BenchmarkRunStatus.interrupted => '중단됨',
};

IconData _statusIcon(BenchmarkRunStatus status) => switch (status) {
  BenchmarkRunStatus.completed => Icons.check_circle_outline,
  BenchmarkRunStatus.running => Icons.hourglass_top,
  BenchmarkRunStatus.cancelled => Icons.cancel_outlined,
  BenchmarkRunStatus.failed ||
  BenchmarkRunStatus.interrupted => Icons.error_outline,
};
