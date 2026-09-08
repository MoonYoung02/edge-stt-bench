import 'dart:io';

import 'package:flutter/material.dart';

import 'benchmark_batch_history_page.dart';
import 'benchmark_batch_page.dart';
import 'benchmark_coordinator.dart';
import 'benchmark_history_page.dart';
import 'benchmark_result_page.dart';
import 'benchmark_run.dart';
import 'benchmark_services.dart';
import 'model_manager_page.dart';
import 'server_manager_page.dart';
import 'server_services.dart';

class BenchmarkHomePage extends StatefulWidget {
  const BenchmarkHomePage({this.coordinator, super.key});

  final BenchmarkCoordinator? coordinator;

  @override
  State<BenchmarkHomePage> createState() => _BenchmarkHomePageState();
}

class _BenchmarkHomePageState extends State<BenchmarkHomePage> {
  final _dataset = AssetDataset();
  final _models = ModelRepository();

  late final BenchmarkCoordinator _coordinator;
  late final bool _ownsCoordinator;
  List<AudioSample> _samples = const [];
  List<DownloadedModel> _downloadedModels = const [];
  AudioSample? _selectedSample;
  DownloadedModel? _selectedModel;
  String _readyStatusText = '데이터셋 확인 중';
  String? _localError;
  bool _initializing = true;
  int _threads = 4;

  bool get _busy => _initializing || _coordinator.isBusy;

  /// Whether [sample] can run against the currently selected model. Always
  /// true until a model is picked, so the audio dropdown isn't pre-emptively
  /// disabled before the user has chosen anything.
  bool _sampleCompatible(AudioSample sample) {
    final engine = _selectedModel?.spec.engine;
    if (engine == null) return true;
    return isAudioCompatibleWithEngine(sample, engine);
  }

  @override
  void initState() {
    super.initState();
    _ownsCoordinator = widget.coordinator == null;
    _coordinator = widget.coordinator ?? BenchmarkCoordinator();
    _coordinator.addListener(_coordinatorChanged);
    _initialize();
  }

  @override
  void dispose() {
    _coordinator.removeListener(_coordinatorChanged);
    if (_ownsCoordinator) _coordinator.dispose();
    super.dispose();
  }

  void _coordinatorChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _initialize() async {
    try {
      await _coordinator.initialize();
      final values = await Future.wait([
        _dataset.loadSamples(),
        _models.downloadedModels(),
      ]);
      final samples = values[0] as List<AudioSample>;
      final downloadedModels = values[1] as List<DownloadedModel>;
      if (!mounted) return;
      setState(() {
        _samples = samples;
        _selectedSample = samples.firstOrNull;
        _downloadedModels = downloadedModels;
        _selectedModel = downloadedModels.firstOrNull;
        _readyStatusText = _readyStatus(samples, downloadedModels);
        _initializing = false;
      });
    } catch (error) {
      _showError(error);
    }
  }

  Future<void> _runBenchmark() async {
    final sample = _selectedSample;
    final model = _selectedModel;
    if (sample == null || model == null || _busy) return;
    setState(() => _localError = null);
    try {
      final run = await _coordinator.run(
        sample: sample,
        model: model,
        threads: _threads,
      );
      if (!mounted || run?.result == null) return;
      await _showResult(run!);
    } catch (error) {
      if (_coordinator.status != '벤치마크 취소됨') _showError(error);
    }
  }

  Future<void> _showResult(BenchmarkRun run) async {
    final result = run.result;
    if (!mounted || result == null) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BenchmarkResultPage(
          result: result,
          run: run,
          repository: _coordinator.results,
          platform: _coordinator.platform,
        ),
      ),
    );
  }

  Future<void> _openHistory() async {
    if (_coordinator.isRunning) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BenchmarkHistoryPage(repository: _coordinator.results),
      ),
    );
  }

  Future<void> _openServerManager() async {
    if (_coordinator.isRunning) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => ServerManagerPage(
          repository: ServerProfileRepository(),
          results: _coordinator.results,
        ),
      ),
    );
  }

  Future<void> _openBatch() async {
    if (_coordinator.isBusy) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BenchmarkBatchPage(
          coordinator: _coordinator,
          samples: _samples,
          downloadedModels: _downloadedModels,
        ),
      ),
    );
  }

  Future<void> _openBatchHistory() async {
    // Viewing past batches is a read-only list; it must stay reachable even
    // while a batch is actively running so the user isn't locked out of
    // their own history just because a new run is in progress.
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => BenchmarkBatchHistoryPage(
          coordinator: _coordinator,
          samples: _samples,
          downloadedModels: _downloadedModels,
        ),
      ),
    );
  }

  Future<void> _openModelManager() async {
    if (_busy) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => ModelManagerPage(repository: _models)),
    );
    await _refreshDownloadedModels();
  }

  Future<void> _refreshDownloadedModels() async {
    final downloadedModels = await _models.downloadedModels();
    if (!mounted) return;
    final selectedId = _selectedModel?.spec.id;
    final selectedModel = downloadedModels
        .where((model) => model.spec.id == selectedId)
        .firstOrNull;
    setState(() {
      _downloadedModels = downloadedModels;
      _selectedModel = selectedModel ?? downloadedModels.firstOrNull;
      _readyStatusText = _readyStatus(_samples, downloadedModels);
    });
  }

  String _readyStatus(
    List<AudioSample> samples,
    List<DownloadedModel> downloadedModels,
  ) {
    if (samples.isEmpty) return '내장 오디오를 찾지 못했습니다';
    if (downloadedModels.isEmpty) return '모델 관리에서 모델을 다운로드하세요';
    return '오디오 ${samples.length}개 · 모델 ${downloadedModels.length}개 준비됨';
  }

  void _showError(Object error) {
    if (!mounted) return;
    setState(() {
      _localError = error is SocketException
          ? '네트워크 연결을 확인해주세요.\n$error'
          : error.toString();
      _initializing = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final latestRun = _coordinator.latestRun;
    final telemetry = _coordinator.latestTelemetry;
    final visibleSamples = _coordinator.liveSamples;
    return Scaffold(
      appBar: AppBar(
        title: const Text('EdgeSTT Mobile Bench'),
        actions: [
          IconButton(
            key: const Key('server-manager-button'),
            tooltip: '서버 관리',
            onPressed: _coordinator.isRunning ? null : _openServerManager,
            icon: const Icon(Icons.cloud_outlined),
          ),
          IconButton(
            key: const Key('batch-history-button'),
            tooltip: '자동 벤치마크 이력',
            onPressed: _openBatchHistory,
            icon: const Icon(Icons.checklist_outlined),
          ),
          IconButton(
            key: const Key('history-button'),
            tooltip: '결과 이력',
            onPressed: _coordinator.isRunning ? null : _openHistory,
            icon: const Icon(Icons.history),
          ),
          IconButton(
            key: const Key('model-manager-button'),
            tooltip: '모델 관리',
            onPressed: _busy ? null : _openModelManager,
            icon: const Icon(Icons.inventory_2_outlined),
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            _StatusCard(
              status: _coordinator.isRunning
                  ? _coordinator.status
                  : _readyStatusText,
              progress: _coordinator.progress,
              modelReady: _downloadedModels.isNotEmpty,
            ),
            if (_coordinator.isRunning) ...[
              const SizedBox(height: 10),
              _LiveMetricsCard(
                telemetry: telemetry,
                samples: visibleSamples,
                onCancel: _coordinator.requestCancel,
              ),
            ],
            const SizedBox(height: 16),
            Text('테스트 설정', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            DropdownButtonFormField<DownloadedModel>(
              key: const Key('model-dropdown'),
              initialValue: _selectedModel,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '다운로드된 모델',
                prefixIcon: Icon(Icons.model_training_outlined),
              ),
              hint: const Text('모델 관리에서 먼저 다운로드하세요'),
              items: _downloadedModels
                  .map(
                    (model) => DropdownMenuItem(
                      value: model,
                      child: Text(
                        '${model.spec.name} · ${engineLabel(model.spec.engine)} · '
                        '${formatBytes(model.spec.sizeBytes)}',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  )
                  .toList(),
              onChanged: _busy
                  ? null
                  : (model) => setState(() => _selectedModel = model),
            ),
            if (_downloadedModels.isEmpty) ...[
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: _busy ? null : _openModelManager,
                  icon: const Icon(Icons.download_outlined),
                  label: const Text('모델 다운로드'),
                ),
              ),
            ],
            const SizedBox(height: 10),
            DropdownButtonFormField<AudioSample>(
              key: const Key('sample-dropdown'),
              initialValue: _selectedSample,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '내장 오디오',
                prefixIcon: Icon(Icons.audio_file_outlined),
              ),
              items: _samples
                  .map(
                    (sample) => DropdownMenuItem(
                      value: sample,
                      enabled: _sampleCompatible(sample),
                      child: Text(
                        _sampleCompatible(sample)
                            ? sample.fileName
                            : '${sample.fileName} · 이 모델은 WAV만 지원',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  )
                  .toList(),
              onChanged: _busy
                  ? null
                  : (sample) => setState(() => _selectedSample = sample),
            ),
            if (_selectedSample != null &&
                !_sampleCompatible(_selectedSample!)) ...[
              const SizedBox(height: 8),
              _CompatibilityNotice(
                message:
                    '${_selectedModel?.spec.name}은(는) 16kHz mono WAV 입력만 '
                    '지원합니다. 다른 오디오를 고르거나 모델을 바꿔주세요.',
              ),
            ],
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
              onChanged: _busy
                  ? null
                  : (threads) => setState(() => _threads = threads ?? 4),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const Key('run-button'),
              onPressed:
                  _busy ||
                      _selectedSample == null ||
                      _selectedModel == null ||
                      !_sampleCompatible(_selectedSample!)
                  ? null
                  : _runBenchmark,
              icon: const Icon(Icons.play_arrow_rounded),
              label: const Padding(
                padding: EdgeInsets.symmetric(vertical: 13),
                child: Text('벤치마크 시작'),
              ),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              key: const Key('batch-run-button'),
              onPressed: _busy ? null : _openBatch,
              icon: const Icon(Icons.playlist_play),
              label: const Text('정답지 있는 샘플 전체 자동 실행'),
            ),
            if (_localError ?? _coordinator.error case final error?) ...[
              const SizedBox(height: 16),
              _ErrorCard(message: error),
            ],
            if (latestRun?.result != null && !_coordinator.isRunning) ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                key: const Key('latest-result-button'),
                onPressed: () => _showResult(latestRun!),
                icon: const Icon(Icons.receipt_long_outlined),
                label: const Text('최근 결과 다시 보기'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({
    required this.status,
    required this.progress,
    required this.modelReady,
  });

  final String status;
  final double? progress;
  final bool modelReady;

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
            Row(
              children: [
                Icon(
                  modelReady
                      ? Icons.check_circle_outline
                      : Icons.downloading_outlined,
                  color: colors.onPrimaryContainer,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    status,
                    style: Theme.of(context).textTheme.titleSmall
                        ?.copyWith(color: colors.onPrimaryContainer),
                  ),
                ),
              ],
            ),
            if (progress case final value?) ...[
              const SizedBox(height: 12),
              LinearProgressIndicator(value: value),
            ],
          ],
        ),
      ),
    );
  }
}

class _LiveMetricsCard extends StatelessWidget {
  const _LiveMetricsCard({
    required this.telemetry,
    required this.samples,
    required this.onCancel,
  });

  final TelemetrySample? telemetry;
  final List<TelemetrySample> samples;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final sample = telemetry;
    String metric(double? value, String unit) =>
        value == null ? 'N/A' : '${value.toStringAsFixed(1)}$unit';
    return Card.outlined(
      key: const Key('live-metrics-card'),
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: _LiveValue(
                    label: '앱 CPU',
                    value: metric(sample?.cpuCoreEquivalentPercent, '%'),
                  ),
                ),
                Expanded(
                  child: _LiveValue(
                    label: 'RAM',
                    value: metric(sample?.memoryMb, 'MB'),
                  ),
                ),
                Expanded(
                  child: _LiveValue(
                    label: '발열',
                    value: (sample?.thermalStatus ?? 'N/A').toUpperCase(),
                  ),
                ),
                Expanded(
                  child: _LiveValue(
                    label: '배터리',
                    value: metric(sample?.batteryTemperatureC, '°C'),
                  ),
                ),
              ],
            ),
            if (samples.length > 1) ...[
              const SizedBox(height: 8),
              SizedBox(
                height: 48,
                width: double.infinity,
                child: CustomPaint(painter: _LiveSparklinePainter(samples)),
              ),
            ],
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: onCancel,
                icon: const Icon(Icons.stop_circle_outlined),
                label: const Text('취소'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LiveValue extends StatelessWidget {
  const _LiveValue({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(height: 3),
        FittedBox(
          child: Text(value, style: Theme.of(context).textTheme.titleSmall),
        ),
      ],
    );
  }
}

class _LiveSparklinePainter extends CustomPainter {
  _LiveSparklinePainter(this.samples);
  final List<TelemetrySample> samples;

  @override
  void paint(Canvas canvas, Size size) {
    final recent = samples.length <= 120
        ? samples
        : samples.sublist(samples.length - 120);
    final values = recent
        .map((sample) => sample.cpuCoreEquivalentPercent)
        .whereType<double>()
        .toList();
    if (values.length < 2) return;
    final maximum = values
        .reduce((a, b) => a > b ? a : b)
        .clamp(1, double.infinity);
    final path = Path();
    for (var index = 0; index < values.length; index++) {
      final x = index / (values.length - 1) * size.width;
      final y = size.height - values[index] / maximum * size.height;
      index == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = Colors.deepOrange
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke,
    );
  }

  @override
  bool shouldRepaint(covariant _LiveSparklinePainter oldDelegate) => true;
}

class _CompatibilityNotice extends StatelessWidget {
  const _CompatibilityNotice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      margin: EdgeInsets.zero,
      color: colors.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(Icons.info_outline, color: colors.onTertiaryContainer, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                message,
                style: TextStyle(color: colors.onTertiaryContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

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
