import 'dart:io';

import 'package:flutter/material.dart';

import 'benchmark_services.dart';

class ModelManagerPage extends StatefulWidget {
  const ModelManagerPage({required this.repository, super.key});

  final ModelRepository repository;

  @override
  State<ModelManagerPage> createState() => _ModelManagerPageState();
}

class _ModelManagerPageState extends State<ModelManagerPage> {
  final Map<String, bool> _downloaded = {};
  String? _busyModelId;
  String? _status;
  String? _error;
  double? _progress;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    final states = <String, bool>{};
    for (final model in modelCatalog) {
      states[model.id] = await widget.repository.isDownloaded(model);
    }
    if (!mounted) return;
    setState(() {
      _downloaded
        ..clear()
        ..addAll(states);
      _loading = false;
    });
  }

  Future<void> _download(ModelSpec model) async {
    if (_busyModelId != null) return;
    if (model.sizeBytes >= 500 * 1000 * 1000) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('대용량 모델 다운로드'),
          content: Text(
            '${model.name}은 ${formatBytes(model.sizeBytes)}입니다. '
            '충분한 저장공간과 RAM이 있는 고사양 기기에서 사용하는 것을 권장합니다.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('취소'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('다운로드'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    setState(() {
      _busyModelId = model.id;
      _status = '다운로드 준비 중';
      _progress = 0;
      _error = null;
    });

    try {
      await widget.repository.downloadModel(
        model,
        onProgress: (value) {
          if (!mounted) return;
          setState(() => _progress = value.clamp(0, 1));
        },
        onStatus: (status) {
          if (!mounted) return;
          setState(() => _status = status);
        },
      );
      await _refresh();
      if (!mounted) return;
      setState(() => _status = '다운로드 및 검증 완료');
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error is SocketException
            ? '네트워크 연결을 확인해주세요.\n$error'
            : error.toString();
        _status = '다운로드 실패';
      });
    } finally {
      if (mounted) {
        setState(() {
          _busyModelId = null;
          _progress = null;
        });
      }
    }
  }

  Future<void> _confirmDelete(ModelSpec model) async {
    if (_busyModelId != null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('모델 삭제'),
        content: Text('${model.name}을 기기에서 삭제할까요?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('삭제'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() {
      _busyModelId = model.id;
      _error = null;
      _status = '모델 삭제 중';
    });
    try {
      await widget.repository.deleteModel(model);
      await _refresh();
      if (mounted) setState(() => _status = '모델 삭제 완료');
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busyModelId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final downloadedCount = _downloaded.values.where((value) => value).length;
    return Scaffold(
      appBar: AppBar(title: const Text('모델 관리')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                children: [
                  Text(
                    '다운로드 완료 $downloadedCount / ${modelCatalog.length}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'SHA-256 검증을 통과한 모델만 벤치마크 화면에서 선택할 수 있습니다.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  if (_error case final error?) ...[
                    const SizedBox(height: 12),
                    Card(
                      color: Theme.of(context).colorScheme.errorContainer,
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Text(error),
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                  for (final model in modelCatalog) ...[
                    _ModelDownloadCard(
                      model: model,
                      downloaded: _downloaded[model.id] ?? false,
                      busy: _busyModelId != null,
                      isCurrent: _busyModelId == model.id,
                      status: _busyModelId == model.id ? _status : null,
                      progress: _busyModelId == model.id ? _progress : null,
                      onDownload: () => _download(model),
                      onDelete: () => _confirmDelete(model),
                    ),
                    const SizedBox(height: 10),
                  ],
                ],
              ),
      ),
    );
  }
}

class _ModelDownloadCard extends StatelessWidget {
  const _ModelDownloadCard({
    required this.model,
    required this.downloaded,
    required this.busy,
    required this.isCurrent,
    required this.onDownload,
    required this.onDelete,
    this.status,
    this.progress,
  });

  final ModelSpec model;
  final bool downloaded;
  final bool busy;
  final bool isCurrent;
  final VoidCallback onDownload;
  final VoidCallback onDelete;
  final String? status;
  final double? progress;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card.outlined(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 10, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  downloaded
                      ? Icons.check_circle_rounded
                      : Icons.cloud_download_outlined,
                  color: downloaded ? colors.primary : colors.outline,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        model.name,
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'GGML ${model.quantization} · ${formatBytes(model.sizeBytes)}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        model.description,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                if (downloaded)
                  IconButton(
                    tooltip: '삭제',
                    onPressed: busy ? null : onDelete,
                    icon: const Icon(Icons.delete_outline),
                  )
                else
                  FilledButton.tonal(
                    onPressed: busy ? null : onDownload,
                    child: const Text('다운로드'),
                  ),
              ],
            ),
            if (isCurrent) ...[
              const SizedBox(height: 12),
              LinearProgressIndicator(value: progress),
              const SizedBox(height: 6),
              Row(
                children: [
                  Expanded(child: Text(status ?? '처리 중')),
                  if (progress case final value?)
                    Text('${(value * 100).toStringAsFixed(0)}%'),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
