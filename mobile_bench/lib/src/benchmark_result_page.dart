import 'package:flutter/material.dart';

import 'benchmark_run.dart';
import 'benchmark_services.dart';
import 'platform_bridge.dart';
import 'result_repository.dart';
import 'server_services.dart';
import 'telemetry_chart.dart';

class BenchmarkResultPage extends StatelessWidget {
  const BenchmarkResultPage({
    required this.result,
    this.run,
    this.repository,
    this.platform,
    super.key,
  });

  final BenchmarkResult result;
  final BenchmarkRun? run;
  final ResultRepository? repository;
  final PlatformBridge? platform;

  Future<void> _export(BuildContext context) async {
    final benchmarkRun = run;
    final resultRepository = repository;
    if (benchmarkRun == null || resultRepository == null) return;
    try {
      final file = await resultRepository.fileFor(benchmarkRun.runId);
      final exported = await (platform ?? PlatformBridge()).exportResult(
        sourcePath: file.path,
        fileName: 'stt-bench-${benchmarkRun.runId}.json',
      );
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            exported == null
                ? '이 플랫폼에서는 내보내기를 지원하지 않습니다.'
                : '내보내기 완료: $exported',
          ),
        ),
      );
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('내보내기 실패: $error')));
    }
  }

  Future<void> _upload(BuildContext context) async {
    final benchmarkRun = run;
    final resultRepository = repository;
    if (benchmarkRun == null || resultRepository == null) return;
    final profiles = ServerProfileRepository();
    final servers = await profiles.list();
    if (!context.mounted) return;
    if (servers.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('서버 관리에서 업로드 서버를 먼저 등록하세요.')),
      );
      return;
    }
    final selected = await showModalBottomSheet<ServerProfile>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(title: Text('전송할 서버 선택')),
            for (final server in servers)
              ListTile(
                leading: Icon(
                  server.isDefault ? Icons.cloud_done : Icons.cloud_outlined,
                ),
                title: Text(server.name),
                subtitle: Text(server.uploadUri.toString()),
                onTap: () => Navigator.pop(context, server),
              ),
          ],
        ),
      ),
    );
    if (selected == null || !context.mounted) return;
    final uploader = BenchmarkUploader(
      profiles: profiles,
      results: resultRepository,
    );
    try {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('${selected.name}에 업로드 중…')));
      await uploader.upload(benchmarkRun, selected);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('${selected.name} 전송 완료')));
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('서버 전송 실패: $error')));
    } finally {
      uploader.close();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: const Key('benchmark-result-page'),
      appBar: AppBar(
        title: const Text('벤치마크 결과'),
        actions: [
          if (run != null && repository != null)
            IconButton(
              key: const Key('upload-result-button'),
              tooltip: '서버 전송',
              onPressed: () => _upload(context),
              icon: const Icon(Icons.cloud_upload_outlined),
            ),
          if (run != null && repository != null)
            IconButton(
              key: const Key('export-result-button'),
              tooltip: 'USB/파일 내보내기',
              onPressed: () => _export(context),
              icon: const Icon(Icons.ios_share_outlined),
            ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            Text(
              result.sample.fileName,
              style: Theme.of(context).textTheme.titleMedium,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: 4),
            Text(
              result.model.spec.name,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _MetricCard(
                    label: '전체 처리',
                    value: formatDuration(result.processingTime),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _MetricCard(
                    label: 'RTF',
                    value: result.rtf?.toStringAsFixed(3) ?? '-',
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _MetricCard(
                    label: 'Segments',
                    value: '${result.segments}',
                  ),
                ),
              ],
            ),
            if (run case final benchmarkRun?) ...[
              const SizedBox(height: 10),
              _TelemetrySummaryCards(run: benchmarkRun),
              const SizedBox(height: 10),
              _DeviceCard(run: benchmarkRun),
              if (benchmarkRun.samples.isNotEmpty) ...[
                const SizedBox(height: 10),
                MetricGraphCard(
                  title: '앱 CPU 사용률',
                  samples: benchmarkRun.samples,
                  value: (sample) => sample.cpuCoreEquivalentPercent,
                  unit: '%',
                  color: Colors.deepOrange,
                ),
                const SizedBox(height: 10),
                MetricGraphCard(
                  title: '앱 메모리(PSS/footprint)',
                  samples: benchmarkRun.samples,
                  value: (sample) => sample.memoryMb,
                  unit: 'MB',
                  color: Colors.indigo,
                ),
                const SizedBox(height: 10),
                MetricGraphCard(
                  title: 'Thermal headroom',
                  samples: benchmarkRun.samples,
                  value: (sample) => sample.thermalHeadroom,
                  unit: '',
                  color: Colors.red,
                ),
                const SizedBox(height: 6),
                Text(
                  '그래프의 세로선은 화면 켜짐/꺼짐 상태가 바뀐 시점입니다.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ],
            const SizedBox(height: 10),
            _TranscriptCard(
              key: const Key('formatted-model-output'),
              title: '모델 출력',
              subtitle: '[시작,종료]  화자ID  성별  문장',
              text: result.formattedTranscript,
            ),
            const SizedBox(height: 10),
            if (result.reference case final reference?)
              _TranscriptCard(
                title: '정답 TXT',
                subtitle: '원본 정답 데이터',
                text: compactReference(reference),
              )
            else
              Card.outlined(
                key: const Key('no-reference-card'),
                margin: EdgeInsets.zero,
                child: const ListTile(
                  leading: Icon(Icons.info_outline),
                  title: Text('정답 TXT 없음'),
                  subtitle: Text('모델 출력과 성능 지표는 정상적으로 표시됩니다.'),
                ),
              ),
            const SizedBox(height: 10),
            Text(
              'asset 준비 ${formatDuration(result.stagingTime)} · '
              '오디오 ${result.audioDuration == null ? '길이 미확인' : formatDuration(result.audioDuration!)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 4),
            Text(
              '전체 처리 시간에는 모델 로딩과 내부 WAV 준비가 포함됩니다.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _TelemetrySummaryCards extends StatelessWidget {
  const _TelemetrySummaryCards({required this.run});

  final BenchmarkRun run;

  @override
  Widget build(BuildContext context) {
    final summary = run.summary;
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        _SmallMetric(
          label: '평균 CPU',
          value: _number(summary.averageCpuPercent, '%'),
        ),
        _SmallMetric(
          label: '최대 CPU',
          value: _number(summary.peakCpuPercent, '%'),
        ),
        _SmallMetric(
          label: '평균 RAM',
          value: _number(summary.averageMemoryMb, 'MB'),
        ),
        _SmallMetric(
          label: 'Peak RAM',
          value: _number(summary.peakMemoryMb, 'MB'),
        ),
        _SmallMetric(
          label: '최대 발열',
          value: (summary.maximumThermalStatus ?? 'N/A').toUpperCase(),
        ),
        _SmallMetric(
          label: '최대 배터리 온도',
          value: _number(summary.maximumBatteryTemperatureC, '°C'),
        ),
      ],
    );
  }
}

class _SmallMetric extends StatelessWidget {
  const _SmallMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 108,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          const SizedBox(height: 3),
          Text(value, style: Theme.of(context).textTheme.titleSmall),
        ],
      ),
    );
  }
}

class _DeviceCard extends StatelessWidget {
  const _DeviceCard({required this.run});

  final BenchmarkRun run;

  @override
  Widget build(BuildContext context) {
    final device = run.device;
    return Card.outlined(
      margin: EdgeInsets.zero,
      child: ListTile(
        leading: const Icon(Icons.phone_android_outlined),
        title: Text(
          [device.manufacturer, device.model].whereType<String>().join(' '),
        ),
        subtitle: Text(
          '${device.osVersion} · ${device.logicalCpuCores} cores · '
          '${run.threads} threads',
        ),
      ),
    );
  }
}

String _number(double? value, String unit) =>
    value == null ? 'N/A' : '${value.toStringAsFixed(1)}$unit';

class _TranscriptCard extends StatelessWidget {
  const _TranscriptCard({
    required this.title,
    required this.subtitle,
    required this.text,
    super.key,
  });

  final String title;
  final String subtitle;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Card.outlined(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 2),
            Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
            const Divider(height: 20),
            SelectableText(
              text,
              style: const TextStyle(fontFamily: 'monospace', height: 1.55),
            ),
          ],
        ),
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Card.filled(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: Theme.of(context).textTheme.labelSmall),
            const SizedBox(height: 5),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(
                value,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
