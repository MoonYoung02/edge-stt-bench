import 'dart:math';

import 'package:flutter/material.dart';

import 'result_repository.dart';
import 'server_services.dart';

class ServerManagerPage extends StatefulWidget {
  const ServerManagerPage({
    required this.repository,
    required this.results,
    super.key,
  });

  final ServerProfileRepository repository;
  final ResultRepository results;

  @override
  State<ServerManagerPage> createState() => _ServerManagerPageState();
}

class _ServerManagerPageState extends State<ServerManagerPage> {
  List<ServerProfile>? _profiles;
  String? _busyId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final profiles = await widget.repository.list();
    if (mounted) setState(() => _profiles = profiles);
  }

  Future<void> _edit([ServerProfile? existing]) async {
    final value = await showDialog<(ServerProfile, String?)>(
      context: context,
      builder: (_) => _ServerEditor(existing: existing),
    );
    if (value == null) return;
    await widget.repository.save(value.$1, bearerToken: value.$2);
    await _load();
  }

  Future<void> _test(ServerProfile profile) async {
    setState(() => _busyId = profile.id);
    final uploader = BenchmarkUploader(
      profiles: widget.repository,
      results: widget.results,
    );
    try {
      final status = await uploader.testConnection(profile);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('서버 응답 확인: HTTP $status')));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('연결 실패: $error')));
    } finally {
      uploader.close();
      if (mounted) setState(() => _busyId = null);
    }
  }

  Future<void> _delete(ServerProfile profile) async {
    await widget.repository.delete(profile);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('서버 관리')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _edit,
        icon: const Icon(Icons.add),
        label: const Text('서버 추가'),
      ),
      body: switch (_profiles) {
        null => const Center(child: CircularProgressIndicator()),
        [] => const Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text('등록된 서버가 없습니다.\n서버 추가를 눌러 업로드 대상을 등록하세요.'),
          ),
        ),
        final profiles => ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
          itemCount: profiles.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (context, index) {
            final profile = profiles[index];
            final busy = _busyId == profile.id;
            return Card.outlined(
              margin: EdgeInsets.zero,
              child: ListTile(
                leading: Icon(
                  profile.isDefault ? Icons.cloud_done : Icons.cloud_outlined,
                ),
                title: Text(profile.name),
                subtitle: Text('${profile.baseUrl}\n${profile.endpoint}'),
                isThreeLine: true,
                onTap: busy ? null : () => _edit(profile),
                trailing: Wrap(
                  children: [
                    IconButton(
                      tooltip: '연결 테스트',
                      onPressed: busy ? null : () => _test(profile),
                      icon: busy
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.wifi_tethering),
                    ),
                    IconButton(
                      tooltip: '삭제',
                      onPressed: busy ? null : () => _delete(profile),
                      icon: const Icon(Icons.delete_outline),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      },
    );
  }
}

class _ServerEditor extends StatefulWidget {
  const _ServerEditor({this.existing});

  final ServerProfile? existing;

  @override
  State<_ServerEditor> createState() => _ServerEditorState();
}

class _ServerEditorState extends State<_ServerEditor> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _baseUrl;
  late final TextEditingController _endpoint;
  late final TextEditingController _token;
  late bool _isDefault;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    _name = TextEditingController(text: existing?.name);
    _baseUrl = TextEditingController(text: existing?.baseUrl ?? 'https://');
    _endpoint = TextEditingController(
      text: existing?.endpoint ?? '/api/v1/benchmark-runs',
    );
    _token = TextEditingController();
    _isDefault = existing?.isDefault ?? false;
  }

  @override
  void dispose() {
    _name.dispose();
    _baseUrl.dispose();
    _endpoint.dispose();
    _token.dispose();
    super.dispose();
  }

  void _save() {
    if (!_formKey.currentState!.validate()) return;
    final existing = widget.existing;
    final id =
        existing?.id ??
        '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(999999)}';
    Navigator.pop(context, (
      ServerProfile(
        id: id,
        name: _name.text.trim(),
        baseUrl: _baseUrl.text.trim(),
        endpoint: _endpoint.text.trim(),
        isDefault: _isDefault,
      ),
      _token.text.trim().isEmpty ? null : _token.text.trim(),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.existing == null ? '서버 추가' : '서버 수정'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: _name,
                  decoration: const InputDecoration(labelText: '서버 이름'),
                  validator: (value) => value == null || value.trim().isEmpty
                      ? '이름을 입력하세요.'
                      : null,
                ),
                const SizedBox(height: 10),
                TextFormField(
                  controller: _baseUrl,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                    labelText: 'Base URL',
                    helperText: 'HTTPS 또는 같은 사설망의 HTTP 주소',
                  ),
                  validator: validateServerBaseUrl,
                ),
                const SizedBox(height: 10),
                TextFormField(
                  controller: _endpoint,
                  decoration: const InputDecoration(labelText: '업로드 endpoint'),
                  validator: (value) => value == null || value.trim().isEmpty
                      ? 'endpoint를 입력하세요.'
                      : null,
                ),
                const SizedBox(height: 10),
                TextFormField(
                  controller: _token,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: widget.existing == null
                        ? 'Bearer token (선택)'
                        : '새 Bearer token (변경할 때만)',
                  ),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _isDefault,
                  onChanged: (value) => setState(() => _isDefault = value),
                  title: const Text('기본 서버로 사용'),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton(onPressed: _save, child: const Text('저장')),
      ],
    );
  }
}
