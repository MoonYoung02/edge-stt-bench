import 'package:flutter/material.dart';

import 'benchmark_batch.dart';
import 'benchmark_coordinator.dart';
import 'benchmark_result_page.dart';
import 'benchmark_services.dart';

/// Configures and runs an automatic benchmark across every KCSC sample that
/// has a reference transcript, or shows the live/final progress of one.
///
/// Pass [existingBatch] to open a batch that already finished (from
/// [BenchmarkBatchHistoryPage]) in a read-only view instead of the
/// configuration form.
class BenchmarkBatchPage extends StatefulWidget {
  const BenchmarkBatchPage({
    required this.coordinator,
    required this.samples,
    required this.downloadedModels,
    this.existingBatch,
    super.key,
  });

  final BenchmarkCoordinator coordinator;
  final List<AudioSample> samples;
  final List<DownloadedModel> downloadedModels;
  final BenchmarkBatch? existingBatch;

  @override
  State<BenchmarkBatchPage> createState() => _BenchmarkBatchPageState();
}

class _BenchmarkBatchPageState extends State<BenchmarkBatchPage> {
  DownloadedModel? _selectedModel;
  int _threads = 4;
  BenchmarkBatch? _displayedBatch;
  String? _error;

  /// Sample asset path → prior completed run id, for [_selectedModel].
  /// Reloaded whenever the model changes so the "already covered" preview
  /// below matches whichever model is currently picked. Empty (not null)
  /// while loading, so the preview just shows nothing rather than a
  /// placeholder flicker.
  Map<String, String> _priorRunIds = const {};

  List<AudioSample> get _labeledSamples => widget.samples
      .where((sample) => sample.referenceAssetPath != null)
      .toList(growable: false);

  int get _alreadyCoveredCount => _labeledSamples
      .where((sample) => _priorRunIds.containsKey(sample.assetPath))
      .length;

  @override
  void initState() {
    super.initState();
    _selectedModel = widget.downloadedModels.firstOrNull;
    _displayedBatch = widget.existingBatch;
    widget.coordinator.addListener(_coordinatorChanged);
    _loadPriorCoverage();
  }

  Future<void> _loadPriorCoverage() async {
    final model = _selectedModel;
    if (model == null) {
      setState(() => _priorRunIds = const {});
      return;
    }
    final priorRunIds = await widget.coordinator.results
        .completedRunIdsBySample(modelId: model.spec.id);
    if (mounted && model == _selectedModel) {
      setState(() => _priorRunIds = priorRunIds);
    }
  }

  @override
  void dispose() {
    widget.coordinator.removeListener(_coordinatorChanged);
    super.dispose();
  }

  void _coordinatorChanged() {
    final active = widget.coordinator.activeBatch;
    if (active != null && mounted) setState(() => _displayedBatch = active);
  }

  Future<void> _start() async {
    final model = _selectedModel;
    if (model == null || widget.coordinator.isBusy) return;
    setState(() {
      _error = null;
      _displayedBatch = null;
    });
    try {
      final batch = await widget.coordinator.runBatch(
        samples: _labeledSamples,
        model: model,
        threads: _threads,
      );
      if (mounted) setState(() => _displayedBatch = batch);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _openEntry(BenchmarkBatchEntry entry) async {
    final runId = entry.runId;
    if (runId == null) return;
    final run = await widget.coordinator.results.get(runId);
    final result = run?.result;
    if (!mounted || run == null || result == null) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BenchmarkResultPage(
          result: result,
          run: run,
          repository: widget.coordinator.results,
          platform: widget.coordinator.platform,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final batch = _displayedBatch;
    final isLive = widget.coordinator.isRunningBatch && batch != null;
    final readOnly = widget.existingBatch != null && !isLive;
    return Scaffold(
      appBar: AppBar(
        title: const Text('자동 벤치마크'),
        actions: [
          if (isLive)
            IconButton(
              tooltip: '취소',
              icon: const Icon(Icons.stop_circle_outlined),
              onPressed: widget.coordinator.requestCancelBatch,
            ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            if (!readOnly) ...[
              Text(
                _alreadyCoveredCount == 0
                    ? '정답 텍스트가 있는 샘플 ${_labeledSamples.length}개를 선택한 '
                          '모델로 순서대로 실행합니다. 발열이 심해도 멈추지 않고 계속 '
                          '진행하며, 그런 샘플은 결과에 표시만 남깁니다.'
                    : '정답 텍스트가 있는 샘플 ${_labeledSamples.length}개 중 '
                          '$_alreadyCoveredCount개는 이 모델로 이미 벤치마크한 적이 있어 '
                          '건너뛰고, 나머지 ${_labeledSamples.length - _alreadyCoveredCount}개만 '
                          '실행합니다. 발열이 심해도 멈추지 않고 계속 진행하며, 그런 '
                          '샘플은 결과에 표시만 남깁니다.',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<DownloadedModel>(
                initialValue: _selectedModel,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: '다운로드된 모델',
                  prefixIcon: Icon(Icons.model_training_outlined),
                ),
                items: widget.downloadedModels
                    .map(
                      (model) => DropdownMenuItem(
                        value: model,
                        child: Text(
                          '${model.spec.name} · ${engineLabel(model.spec.engine)}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    )
                    .toList(),
                onChanged: widget.coordinator.isBusy
                    ? null
                    : (model) {
                        setState(() => _selectedModel = model);
                        _loadPriorCoverage();
                      },
              ),
              const SizedBox(height: 10),
              DropdownButtonFormField<int>(
                initialValue: _threads,
                decoration: const InputDecoration(
                  labelText: 'CPU threads',
                  prefixIcon: Icon(Icons.memory_outlined),
                ),
                items: const [1, 2, 4, 6, 8]
                    .map(
                      (threads) => DropdownMenuItem(
                        value: threads,
                        child: Text('$threads threads'),
                      ),
                    )
                    .toList(),
                onChanged: widget.coordinator.isBusy
                    ? null
                    : (threads) => setState(() => _threads = threads ?? 4),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed:
                    widget.coordinator.isBusy ||
                        _selectedModel == null ||
                        _labeledSamples.isEmpty
                    ? null
                    : _start,
                icon: const Icon(Icons.playlist_play),
                label: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 13),
                  child: Text(
                    _alreadyCoveredCount == 0
                        ? '샘플 ${_labeledSamples.length}개 자동 실행'
                        : '샘플 ${_labeledSamples.length - _alreadyCoveredCount}개 '
                              '자동 실행 (기존 $_alreadyCoveredCount개 재사용)',
                  ),
                ),
              ),
              if (_error case final error?) ...[
                const SizedBox(height: 12),
                _ErrorCard(message: error),
              ],
              const SizedBox(height: 20),
            ],
            if (batch != null) ...[
              _BatchSummaryCard(batch: batch),
              if (isLive) ...[
                const SizedBox(height: 8),
                _LiveSampleStatusCard(
                  status: widget.coordinator.status,
                  progress: widget.coordinator.progress,
                ),
              ],
              const SizedBox(height: 12),
              ...batch.entries.map(
                (entry) => _BatchEntryTile(
                  entry: entry,
                  liveStatus: isLive && entry.status == BenchmarkBatchEntryStatus.running
                      ? widget.coordinator.status
                      : null,
                  liveProgress: isLive && entry.status == BenchmarkBatchEntryStatus.running
                      ? widget.coordinator.progress
                      : null,
                  onTap: entry.runId == null ? null : () => _openEntry(entry),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _BatchSummaryCard extends StatelessWidget {
  const _BatchSummaryCard({required this.batch});
  final BenchmarkBatch batch;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      margin: EdgeInsets.zero,
      color: colors.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _modelName(batch.modelId),
              style: Theme.of(
                context,
              ).textTheme.titleSmall?.copyWith(color: colors.onPrimaryContainer),
            ),
            const SizedBox(height: 6),
            Text(
              '${batch.completedCount}/${batch.totalCount} 완료'
              '${batch.failedCount > 0 ? ' · 실패 ${batch.failedCount}' : ''}'
              ' · ${batch.threads} threads',
              style: TextStyle(color: colors.onPrimaryContainer),
            ),
            const SizedBox(height: 10),
            LinearProgressIndicator(
              value: batch.totalCount == 0
                  ? 0
                  : (batch.completedCount + batch.failedCount) /
                        batch.totalCount,
            ),
          ],
        ),
      ),
    );
  }
}

/// Surfaces the same live status/percentage the single-run home screen
/// shows (`BenchmarkCoordinator.status`/`.progress`), so a long-running
/// sample doesn't look stuck just because the batch list only shows a
/// static "실행 중" label per entry.
class _LiveSampleStatusCard extends StatelessWidget {
  const _LiveSampleStatusCard({required this.status, required this.progress});
  final String status;
  final double? progress;

  @override
  Widget build(BuildContext context) {
    return Card.outlined(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(status, style: Theme.of(context).textTheme.bodyMedium),
            if (progress != null) ...[
              const SizedBox(height: 8),
              LinearProgressIndicator(value: progress),
            ],
          ],
        ),
      ),
    );
  }
}

class _BatchEntryTile extends StatelessWidget {
  const _BatchEntryTile({
    required this.entry,
    this.onTap,
    this.liveStatus,
    this.liveProgress,
  });
  final BenchmarkBatchEntry entry;
  final VoidCallback? onTap;

  /// Current sample's live status text (e.g. "STT 실행 중 · 42%") and
  /// progress (0-1), taken from [BenchmarkCoordinator.status]/`.progress`.
  /// Non-null only while this entry is the one actively running, so a long
  /// KCSC sample (files run ~15 minutes on average) doesn't just look stuck.
  final String? liveStatus;
  final double? liveProgress;

  @override
  Widget build(BuildContext context) {
    return Card.outlined(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(
          children: [
            ListTile(
              leading: Icon(
                entry.reusedFromPriorRun ? Icons.history : _icon(entry.status),
              ),
              title: Text(entry.sampleId, overflow: TextOverflow.ellipsis),
              subtitle: liveStatus != null
                  ? Text(liveStatus!, overflow: TextOverflow.ellipsis)
                  : entry.reusedFromPriorRun
                  ? const Text('이전 실행 결과 재사용')
                  : entry.error != null
                  ? Text(
                      entry.error!,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    )
                  : entry.thermalThrottled
                  ? const Text('발열 상태에서 측정됨')
                  : null,
              trailing: Text(
                entry.reusedFromPriorRun ? '재사용' : _label(entry.status),
              ),
              onTap: onTap,
            ),
            if (liveProgress != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: LinearProgressIndicator(value: liveProgress),
              ),
          ],
        ),
      ),
    );
  }

  IconData _icon(BenchmarkBatchEntryStatus status) => switch (status) {
    BenchmarkBatchEntryStatus.pending => Icons.schedule_outlined,
    BenchmarkBatchEntryStatus.running => Icons.hourglass_top,
    BenchmarkBatchEntryStatus.completed => Icons.check_circle_outline,
    BenchmarkBatchEntryStatus.failed => Icons.error_outline,
    BenchmarkBatchEntryStatus.skipped => Icons.remove_circle_outline,
  };

  String _label(BenchmarkBatchEntryStatus status) => switch (status) {
    BenchmarkBatchEntryStatus.pending => '대기',
    BenchmarkBatchEntryStatus.running => '실행 중',
    BenchmarkBatchEntryStatus.completed => '완료',
    BenchmarkBatchEntryStatus.failed => '실패',
    BenchmarkBatchEntryStatus.skipped => '건너뜀',
  };
}

String _modelName(String modelId) =>
    modelCatalog
        .where((model) => model.id == modelId)
        .map((model) => model.name)
        .firstOrNull ??
    modelId;

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      margin: EdgeInsets.zero,
      color: colors.errorContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(message, style: TextStyle(color: colors.onErrorContainer)),
      ),
    );
  }
}
