import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_bench/src/benchmark_run.dart';
import 'package:mobile_bench/src/benchmark_services.dart';
import 'package:mobile_bench/src/result_repository.dart';
import 'package:mobile_bench/src/server_services.dart';

void main() {
  BenchmarkRun createRun() {
    final result = BenchmarkResult(
      sample: const AudioSample(assetPath: 'assets/data/sample.m4a'),
      transcript: '테스트',
      formattedTranscript: '[0.000,1.000]\tPRED\tunknown\t테스트',
      transcriptSegments: const [
        BenchmarkSegment(
          from: Duration.zero,
          to: Duration(seconds: 1),
          text: '테스트',
        ),
      ],
      stagingTime: const Duration(milliseconds: 20),
      processingTime: const Duration(seconds: 2),
      audioDuration: const Duration(seconds: 4),
      model: DownloadedModel(
        spec: modelCatalog.first,
        file: File('/models/model.bin'),
      ),
      segments: 1,
    );
    return BenchmarkRun(
      runId: 'run-1',
      status: BenchmarkRunStatus.completed,
      startedAt: DateTime.utc(2026, 9, 6),
      completedAt: DateTime.utc(2026, 9, 6, 0, 1),
      sampleAssetPath: result.sample.assetPath,
      modelId: modelCatalog.first.id,
      modelPath: result.model.file.path,
      threads: 4,
      device: const DeviceMetadata(
        platform: 'android',
        manufacturer: 'Samsung',
        model: 'SM-G991N',
        osVersion: 'Android 15',
        logicalCpuCores: 8,
        totalMemoryBytes: 8 * 1000 * 1000 * 1000,
      ),
      result: result,
      samples: const [
        TelemetrySample(
          elapsedMs: 500,
          phase: BenchmarkPhase.inference,
          progress: 0.25,
          appLifecycle: 'resumed',
          cpuCoreEquivalentPercent: 200,
          memoryMb: 300,
          thermalStatus: 'light',
          batteryTemperatureC: 32,
          screenInteractive: true,
        ),
        TelemetrySample(
          elapsedMs: 1000,
          phase: BenchmarkPhase.inference,
          progress: 0.5,
          appLifecycle: 'paused',
          cpuCoreEquivalentPercent: 400,
          memoryMb: 500,
          thermalStatus: 'serious',
          batteryTemperatureC: 37,
          screenInteractive: false,
        ),
      ],
    );
  }

  test('benchmark run JSON round-trips result and telemetry', () {
    final run = createRun();
    final restored = BenchmarkRun.fromJson(
      Map<String, dynamic>.from(jsonDecode(jsonEncode(run.toJson())) as Map),
    );

    expect(restored.runId, run.runId);
    expect(restored.status, BenchmarkRunStatus.completed);
    expect(restored.result?.transcript, '테스트');
    expect(restored.result?.rtf, 0.5);
    expect(restored.samples, hasLength(2));
    expect(restored.samples.last.screenInteractive, isFalse);
    expect(restored.summary.averageCpuPercent, 300);
    expect(restored.summary.peakMemoryMb, 500);
    expect(restored.summary.maximumThermalStatus, 'serious');
  });

  test(
    'result repository persists and marks abandoned runs interrupted',
    () async {
      final temporary = await Directory.systemTemp.createTemp(
        'stt-bench-test-',
      );
      addTearDown(() => temporary.delete(recursive: true));
      final repository = ResultRepository(
        directoryProvider: () async => temporary,
      );
      final run = createRun()
        ..status = BenchmarkRunStatus.running
        ..completedAt = null
        ..result = null;

      await repository.save(run);
      await repository.markInterruptedRuns();
      final stored = await repository.list();

      expect(stored, hasLength(1));
      expect(stored.single.status, BenchmarkRunStatus.interrupted);
      expect(stored.single.completedAt, isNotNull);
      expect(stored.single.error, contains('앱 프로세스'));
    },
  );

  test('server uploader sends JSON, token and idempotency key', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final temporary = await Directory.systemTemp.createTemp('stt-server-test-');
    addTearDown(() => temporary.delete(recursive: true));
    final results = ResultRepository(directoryProvider: () async => temporary);
    final profiles = ServerProfileRepository(
      directoryProvider: () async => temporary,
    );
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(server.close);
    final received = Completer<HttpRequest>();
    server.listen((request) async {
      received.complete(request);
      await utf8.decoder.bind(request).join();
      request.response
        ..statusCode = HttpStatus.created
        ..write('{"accepted":true}');
      await request.response.close();
    });
    final profile = ServerProfile(
      id: 'local',
      name: 'Local test',
      baseUrl: 'http://${server.address.address}:${server.port}',
      endpoint: '/runs',
    );
    await profiles.save(profile, bearerToken: 'test-token');
    final uploader = BenchmarkUploader(profiles: profiles, results: results);
    addTearDown(uploader.close);

    final response = await uploader.upload(createRun(), profile);
    final request = await received.future;

    expect(response, contains('accepted'));
    expect(request.method, 'POST');
    expect(request.uri.path, '/runs');
    expect(request.headers.value('Idempotency-Key'), 'run-1');
    expect(
      request.headers.value(HttpHeaders.authorizationHeader),
      'Bearer test-token',
    );
    expect(request.headers.contentType?.mimeType, ContentType.json.mimeType);
  });

  test('server URL validation permits only HTTPS or local HTTP', () {
    expect(validateServerBaseUrl('https://bench.example.com'), isNull);
    expect(validateServerBaseUrl('http://192.168.0.5:8787'), isNull);
    expect(validateServerBaseUrl('http://127.0.0.1:8787'), isNull);
    expect(validateServerBaseUrl('http://10.0.2.2:8787'), isNull);
    expect(validateServerBaseUrl('http://bench-mac.local:8787'), isNull);
    expect(validateServerBaseUrl('http://example.com:8787'), isNotNull);
    expect(validateServerBaseUrl('not a url'), isNotNull);
  });
}
