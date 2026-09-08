import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa_onnx;

import 'benchmark_services.dart';

/// Runs sherpa-onnx models (Korean streaming Zipformer, offline SenseVoice)
/// against a single [AudioSample].
///
/// Mirrors [WhisperBenchmarkEngine.run]'s signature and [BenchmarkResult]
/// shape exactly, so [BenchmarkCoordinator] and everything downstream
/// (telemetry, result storage, history/result UI, desktop import) needs no
/// changes to support a second engine.
///
/// Only plain 16 kHz mono 16-bit PCM WAV input is supported for now — every
/// KCSC sample already is that format. Other containers/codecs throw;
/// whisper.cpp's FFmpeg normalization step is not reused here yet.
class SherpaOnnxEngine implements SttBenchmarkEngine {
  SherpaOnnxEngine({ModelRepository? repository})
    : _repository = repository ?? ModelRepository();

  final ModelRepository _repository;
  bool _bindingsReady = false;

  /// Samples per streaming chunk fed to the online recognizer (100ms @
  /// 16kHz), matching a realistic partial-result cadence for a live caption
  /// UI rather than decoding the whole file in one call.
  static const int _streamingChunkSamples = 1600;

  @override
  Future<BenchmarkResult> run({
    required AudioSample sample,
    required DownloadedModel model,
    required int threads,
    required void Function(int value) onProgress,
    void Function()? onInferenceStarted,
  }) async {
    final staged = await AssetDataset().stage(sample);
    try {
      if (!staged.file.path.toLowerCase().endsWith('.wav')) {
        throw UnsupportedError(
          'sherpa-onnx 엔진은 현재 16kHz mono WAV 입력만 지원합니다: '
          '${sample.fileName}',
        );
      }
      final bytes = await staged.file.readAsBytes();
      final wav = _decodeWav(ByteData.sublistView(bytes));
      if (wav == null) {
        throw const FormatException('WAV 파형을 해석할 수 없습니다.');
      }
      if (wav.sampleRate != 16000) {
        throw UnsupportedError(
          'sherpa-onnx 엔진은 16000Hz 입력만 지원합니다 (실제: ${wav.sampleRate}Hz).',
        );
      }

      if (!_bindingsReady) {
        sherpa_onnx.initBindings();
        _bindingsReady = true;
      }
      final files = await _repository.resolvedModelFiles(model.spec);
      final byName = {for (final file in files) file.path.split('/').last: file.path};

      final (segments, elapsed) = switch (model.spec.engine) {
        SttEngineKind.sherpaOnnxStreaming => _runStreaming(
          byName: byName,
          samples: wav.samples,
          sampleRate: wav.sampleRate,
          threads: threads,
          onProgress: onProgress,
          onInferenceStarted: onInferenceStarted,
        ),
        SttEngineKind.sherpaOnnxOffline => _runOffline(
          byName: byName,
          samples: wav.samples,
          sampleRate: wav.sampleRate,
          threads: threads,
          onProgress: onProgress,
          onInferenceStarted: onInferenceStarted,
        ),
        SttEngineKind.whisperCpp => throw StateError(
          'SherpaOnnxEngine에는 whisper.cpp 모델을 넣을 수 없습니다.',
        ),
      };

      final transcript = segments.map((segment) => segment.text).join(' ').trim();
      return BenchmarkResult(
        sample: sample,
        transcript: transcript,
        formattedTranscript: formatPredictionTranscript(
          segments: segments,
          transcript: transcript,
          reference: staged.reference,
          audioDuration: staged.audioDuration,
        ),
        transcriptSegments: segments,
        reference: staged.reference,
        stagingTime: staged.stagingTime,
        processingTime: elapsed,
        audioDuration: staged.audioDuration,
        model: model,
        segments: segments.length,
      );
    } finally {
      if (await staged.file.exists()) await staged.file.delete();
    }
  }

  /// Feeds [samples] to an [sherpa_onnx.OnlineRecognizer] in small chunks,
  /// finalizing a segment every time the endpointer fires — the same shape
  /// a live captioning UI would see, just replayed from a file instead of a
  /// microphone.
  (List<BenchmarkSegment>, Duration) _runStreaming({
    required Map<String, String> byName,
    required Float32List samples,
    required int sampleRate,
    required int threads,
    required void Function(int value) onProgress,
    void Function()? onInferenceStarted,
  }) {
    final config = sherpa_onnx.OnlineRecognizerConfig(
      model: sherpa_onnx.OnlineModelConfig(
        transducer: sherpa_onnx.OnlineTransducerModelConfig(
          encoder: byName['encoder-epoch-99-avg-1.int8.onnx']!,
          decoder: byName['decoder-epoch-99-avg-1.int8.onnx']!,
          joiner: byName['joiner-epoch-99-avg-1.int8.onnx']!,
        ),
        tokens: byName['tokens.txt']!,
        modelType: 'zipformer',
        numThreads: threads,
      ),
    );
    final recognizer = sherpa_onnx.OnlineRecognizer(config);
    final stream = recognizer.createStream();
    onInferenceStarted?.call();
    final stopwatch = Stopwatch()..start();
    try {
      final segments = <BenchmarkSegment>[];
      final total = samples.length;
      var chunkStart = 0;
      var segmentStartSeconds = 0.0;
      while (chunkStart < total) {
        final chunkEnd = (chunkStart + _streamingChunkSamples).clamp(0, total);
        stream.acceptWaveform(
          samples: Float32List.sublistView(samples, chunkStart, chunkEnd),
          sampleRate: sampleRate,
        );
        while (recognizer.isReady(stream)) {
          recognizer.decode(stream);
        }
        if (recognizer.isEndpoint(stream)) {
          final text = recognizer.getResult(stream).text.trim();
          final endSeconds = chunkEnd / sampleRate;
          if (text.isNotEmpty) {
            segments.add(
              BenchmarkSegment(
                from: _secondsToDuration(segmentStartSeconds),
                to: _secondsToDuration(endSeconds),
                text: text,
              ),
            );
          }
          segmentStartSeconds = endSeconds;
          recognizer.reset(stream);
        }
        chunkStart = chunkEnd;
        onProgress(total == 0 ? 100 : (chunkStart / total * 100).round());
      }
      // The tail after the last endpoint never finalized; keep it rather
      // than silently dropping whatever the model already recognized.
      final tailText = recognizer.getResult(stream).text.trim();
      if (tailText.isNotEmpty) {
        segments.add(
          BenchmarkSegment(
            from: _secondsToDuration(segmentStartSeconds),
            to: _secondsToDuration(total / sampleRate),
            text: tailText,
          ),
        );
      }
      stopwatch.stop();
      return (segments, stopwatch.elapsed);
    } finally {
      stream.free();
      recognizer.free();
    }
  }

  /// Feeds the whole file to an [sherpa_onnx.OfflineRecognizer] in one call —
  /// SenseVoice is a batch model, there is no partial/streaming result to
  /// report.
  (List<BenchmarkSegment>, Duration) _runOffline({
    required Map<String, String> byName,
    required Float32List samples,
    required int sampleRate,
    required int threads,
    required void Function(int value) onProgress,
    void Function()? onInferenceStarted,
  }) {
    final config = sherpa_onnx.OfflineRecognizerConfig(
      model: sherpa_onnx.OfflineModelConfig(
        senseVoice: sherpa_onnx.OfflineSenseVoiceModelConfig(
          model: byName['model.int8.onnx']!,
          language: 'ko',
          useInverseTextNormalization: false,
        ),
        tokens: byName['tokens.txt']!,
        numThreads: threads,
      ),
    );
    final recognizer = sherpa_onnx.OfflineRecognizer(config);
    onInferenceStarted?.call();
    onProgress(0);
    final stopwatch = Stopwatch()..start();
    final stream = recognizer.createStream();
    try {
      stream.acceptWaveform(samples: samples, sampleRate: sampleRate);
      recognizer.decode(stream);
      final text = recognizer.getResult(stream).text.trim();
      stopwatch.stop();
      onProgress(100);
      final segments = text.isEmpty
          ? const <BenchmarkSegment>[]
          : [
              BenchmarkSegment(
                from: Duration.zero,
                to: _secondsToDuration(samples.length / sampleRate),
                text: text,
              ),
            ];
      return (segments, stopwatch.elapsed);
    } finally {
      stream.free();
      recognizer.free();
    }
  }
}

Duration _secondsToDuration(double seconds) =>
    Duration(microseconds: (seconds * Duration.microsecondsPerSecond).round());

class _WavAudio {
  const _WavAudio({required this.sampleRate, required this.samples});
  final int sampleRate;
  final Float32List samples;
}

/// Minimal RIFF/WAVE reader: mono 16-bit PCM only (every KCSC sample already
/// is). Returns null for anything else instead of guessing.
_WavAudio? _decodeWav(ByteData bytes) {
  if (bytes.lengthInBytes < 44 ||
      _fourCc(bytes, 0) != 'RIFF' ||
      _fourCc(bytes, 8) != 'WAVE') {
    return null;
  }

  var offset = 12;
  int? sampleRate;
  int? bitsPerSample;
  int? channels;
  int? dataOffset;
  int? dataSize;

  while (offset + 8 <= bytes.lengthInBytes) {
    final id = _fourCc(bytes, offset);
    final size = bytes.getUint32(offset + 4, Endian.little);
    final body = offset + 8;
    if (body + size > bytes.lengthInBytes) break;

    if (id == 'fmt ' && size >= 16) {
      channels = bytes.getUint16(body + 2, Endian.little);
      sampleRate = bytes.getUint32(body + 4, Endian.little);
      bitsPerSample = bytes.getUint16(body + 14, Endian.little);
    } else if (id == 'data') {
      dataOffset = body;
      dataSize = size;
    }
    offset = body + size + (size.isOdd ? 1 : 0);
  }

  if (sampleRate == null ||
      bitsPerSample != 16 ||
      channels != 1 ||
      dataOffset == null ||
      dataSize == null) {
    return null;
  }

  final sampleCount = dataSize ~/ 2;
  final samples = Float32List(sampleCount);
  for (var i = 0; i < sampleCount; i++) {
    samples[i] = bytes.getInt16(dataOffset + i * 2, Endian.little) / 32768.0;
  }
  return _WavAudio(sampleRate: sampleRate, samples: samples);
}

String _fourCc(ByteData bytes, int offset) {
  return String.fromCharCodes(
    List<int>.generate(4, (index) => bytes.getUint8(offset + index)),
  );
}
