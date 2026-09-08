import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_bench/main.dart';
import 'package:mobile_bench/src/benchmark_result_page.dart';
import 'package:mobile_bench/src/benchmark_services.dart';
import 'package:mobile_bench/src/model_manager_page.dart';

void main() {
  test('recognizes the supported audio file extensions', () {
    const expected = {
      '.wav',
      '.m4a',
      '.mp3',
      '.flac',
      '.ogg',
      '.opus',
      '.aac',
      '.mp4',
      '.webm',
    };

    expect(supportedAudioExtensions, containsAll(expected));
    expect(
      const AudioSample(assetPath: 'assets/data/한글 녹음.M4A').extension,
      '.m4a',
    );
  });

  test('model catalog has reproducible download metadata', () {
    expect(modelCatalog.map((model) => model.id).toSet(), hasLength(13));
    for (final model in modelCatalog) {
      expect(model.url, startsWith('https://'));
      expect(model.sha256, hasLength(64));
      expect(model.sizeBytes, greaterThan(0));
      expect(model.description, isNotEmpty);
      switch (model.engine) {
        case SttEngineKind.whisperCpp:
          expect(model.fileName, endsWith('.bin'));
          expect(model.quantization, isNotEmpty);
          expect(model.whisperModel, isNotNull);
          expect(model.archiveModelFiles, isEmpty);
        case SttEngineKind.sherpaOnnxStreaming:
        case SttEngineKind.sherpaOnnxOffline:
          expect(model.fileName, endsWith('.tar.bz2'));
          expect(model.whisperModel, isNull);
          expect(model.archiveModelFiles, isNotEmpty);
      }
    }
  });

  test('formats predictions like the reference transcript rows', () {
    final output = formatPredictionTranscript(
      segments: const [
        BenchmarkSegment(
          from: Duration(milliseconds: 1230),
          to: Duration(milliseconds: 4560),
          text: ' 안녕하세요 ',
        ),
      ],
      transcript: '안녕하세요',
      reference: '[0.000,1.000]\tG0101\tmale\t정답',
    );

    expect(output, '[1.230,4.560]\tG0101\tmale\t안녕하세요');
  });

  testWidgets('shows the benchmark shell', (tester) async {
    await tester.pumpWidget(const BenchmarkApp());

    expect(find.text('STT Mobile Bench'), findsOneWidget);
    expect(find.text('테스트 설정'), findsOneWidget);
    expect(find.byKey(const Key('model-manager-button')), findsOneWidget);
    expect(find.byKey(const Key('model-dropdown')), findsOneWidget);
    expect(find.byKey(const Key('run-button')), findsOneWidget);
  });

  testWidgets('model manager shows catalog and installed state', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(home: ModelManagerPage(repository: _FakeModelRepository())),
    );
    await tester.pumpAndSettle();

    expect(find.text('모델 관리'), findsOneWidget);
    expect(find.text('다운로드 완료 1 / 13'), findsOneWidget);
    expect(find.text('Whisper Tiny Q5_1'), findsOneWidget);
    expect(find.text('Whisper Tiny Q8_0'), findsOneWidget);
    expect(find.text('Whisper Base Q5_1'), findsOneWidget);
    expect(find.text('다운로드'), findsWidgets);
  });

  testWidgets('result page renders without a reference transcript', (
    tester,
  ) async {
    final result = BenchmarkResult(
      sample: const AudioSample(assetPath: 'assets/data/recording.m4a'),
      transcript: '테스트 문장',
      formattedTranscript: '[0.000,1.500]\tPRED\tunknown\t테스트 문장',
      transcriptSegments: const [
        BenchmarkSegment(
          from: Duration.zero,
          to: Duration(milliseconds: 1500),
          text: '테스트 문장',
        ),
      ],
      stagingTime: const Duration(milliseconds: 10),
      processingTime: const Duration(seconds: 1),
      model: DownloadedModel(
        spec: modelCatalog.first,
        file: File('/tmp/ggml-tiny-q5_1.bin'),
      ),
      segments: 1,
      audioDuration: const Duration(milliseconds: 1500),
    );

    await tester.pumpWidget(
      MaterialApp(home: BenchmarkResultPage(result: result)),
    );

    expect(find.byKey(const Key('benchmark-result-page')), findsOneWidget);
    expect(find.byKey(const Key('formatted-model-output')), findsOneWidget);
    expect(find.byKey(const Key('no-reference-card')), findsOneWidget);
    expect(find.text('정답 TXT 없음'), findsOneWidget);
  });
}

class _FakeModelRepository extends ModelRepository {
  @override
  Future<bool> isDownloaded(ModelSpec model) async {
    return model.id == 'whisper-base-q5_1';
  }
}
