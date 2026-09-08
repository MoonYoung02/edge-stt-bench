import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path_provider/path_provider.dart';

import 'benchmark_run.dart';
import 'result_repository.dart';

String? validateServerBaseUrl(String? value) {
  final uri = Uri.tryParse(value?.trim() ?? '');
  if (uri == null || uri.host.isEmpty) {
    return '올바른 서버 주소를 입력하세요.';
  }
  if (uri.scheme == 'https') return null;
  if (uri.scheme == 'http' && _isLocalDevelopmentHost(uri.host)) return null;
  return 'HTTPS 또는 사설망의 HTTP 주소를 입력하세요.';
}

bool _isLocalDevelopmentHost(String host) {
  final normalized = host.toLowerCase();
  if (normalized == 'localhost' ||
      normalized == '::1' ||
      normalized == '10.0.2.2' ||
      normalized.endsWith('.local') ||
      normalized.startsWith('fe80:')) {
    return true;
  }
  final parts = normalized.split('.');
  if (parts.length != 4) return false;
  final octets = parts.map(int.tryParse).toList();
  if (octets.any((part) => part == null || part < 0 || part > 255)) {
    return false;
  }
  final first = octets[0]!;
  final second = octets[1]!;
  return first == 10 ||
      first == 127 ||
      (first == 172 && second >= 16 && second <= 31) ||
      (first == 192 && second == 168) ||
      (first == 169 && second == 254);
}

class ServerProfile {
  const ServerProfile({
    required this.id,
    required this.name,
    required this.baseUrl,
    this.endpoint = '/api/v1/benchmark-runs',
    this.isDefault = false,
  });

  factory ServerProfile.fromJson(Map<String, dynamic> json) => ServerProfile(
    id: json['id'] as String,
    name: json['name'] as String,
    baseUrl: json['baseUrl'] as String,
    endpoint: json['endpoint'] as String? ?? '/api/v1/benchmark-runs',
    isDefault: json['isDefault'] as bool? ?? false,
  );

  final String id;
  final String name;
  final String baseUrl;
  final String endpoint;
  final bool isDefault;

  ServerProfile copyWith({bool? isDefault}) => ServerProfile(
    id: id,
    name: name,
    baseUrl: baseUrl,
    endpoint: endpoint,
    isDefault: isDefault ?? this.isDefault,
  );

  Uri get uploadUri {
    final base = Uri.parse(baseUrl.endsWith('/') ? baseUrl : '$baseUrl/');
    return base.resolve(
      endpoint.startsWith('/') ? endpoint.substring(1) : endpoint,
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'baseUrl': baseUrl,
    'endpoint': endpoint,
    'isDefault': isDefault,
  };
}

class ServerProfileRepository {
  ServerProfileRepository({
    FlutterSecureStorage? secureStorage,
    Future<Directory> Function()? directoryProvider,
  }) : _secureStorage = secureStorage ?? const FlutterSecureStorage(),
       _directoryProvider = directoryProvider ?? getApplicationSupportDirectory;

  final FlutterSecureStorage _secureStorage;
  final Future<Directory> Function() _directoryProvider;

  Future<File> _file() async {
    final directory = await _directoryProvider();
    await directory.create(recursive: true);
    return File('${directory.path}/servers.json');
  }

  Future<List<ServerProfile>> list() async {
    final file = await _file();
    if (!await file.exists()) return const [];
    final value = jsonDecode(await file.readAsString()) as List<dynamic>;
    return value
        .map(
          (item) =>
              ServerProfile.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  Future<void> save(ServerProfile profile, {String? bearerToken}) async {
    final profiles = [...await list()];
    profiles.removeWhere((value) => value.id == profile.id);
    if (profile.isDefault) {
      for (var index = 0; index < profiles.length; index++) {
        profiles[index] = profiles[index].copyWith(isDefault: false);
      }
    }
    profiles.add(profile);
    profiles.sort((a, b) => a.name.compareTo(b.name));
    await (await _file()).writeAsString(
      const JsonEncoder.withIndent('  ')
          .convert(profiles.map((value) => value.toJson()).toList()),
      flush: true,
    );
    if (bearerToken != null && bearerToken.isNotEmpty) {
      await _secureStorage.write(
        key: _tokenKey(profile.id),
        value: bearerToken,
      );
    }
  }

  Future<String?> token(String serverId) =>
      _secureStorage.read(key: _tokenKey(serverId));

  Future<void> delete(ServerProfile profile) async {
    final profiles = [...await list()]
      ..removeWhere((value) => value.id == profile.id);
    await (await _file()).writeAsString(
      jsonEncode(profiles.map((value) => value.toJson()).toList()),
      flush: true,
    );
    await _secureStorage.delete(key: _tokenKey(profile.id));
  }

  String _tokenKey(String serverId) => 'benchmark_server_token_$serverId';
}

class BenchmarkUploader {
  BenchmarkUploader({
    required this.profiles,
    required this.results,
    HttpClient? client,
  }) : _client = client ?? HttpClient();

  final ServerProfileRepository profiles;
  final ResultRepository results;
  final HttpClient _client;

  Future<String> upload(BenchmarkRun run, ServerProfile server) async {
    final request = await _client
        .postUrl(server.uploadUri)
        .timeout(const Duration(seconds: 20));
    request.headers
      ..contentType = ContentType.json
      ..set('Idempotency-Key', run.runId);
    final token = await profiles.token(server.id);
    if (token != null && token.isNotEmpty) {
      request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
    }
    request.add(utf8.encode(jsonEncode(run.toJson())));
    final response = await request.close().timeout(const Duration(seconds: 60));
    final body = await utf8.decoder.bind(response).join();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HttpException(
        '업로드 실패: HTTP ${response.statusCode}${body.isEmpty ? '' : ' · $body'}',
        uri: server.uploadUri,
      );
    }
    return body;
  }

  Future<int> testConnection(ServerProfile server) async {
    final base = Uri.parse(server.baseUrl);
    final request = await _client
        .getUrl(base)
        .timeout(const Duration(seconds: 10));
    final response = await request.close().timeout(const Duration(seconds: 10));
    await response.drain<void>();
    return response.statusCode;
  }

  void close() => _client.close(force: true);
}
