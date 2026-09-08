import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:whisper_ggml/whisper_ggml.dart';

const String _whisperRepositoryUrl =
    'https://huggingface.co/ggerganov/whisper.cpp/resolve/'
    '5359861c739e955e79d9a303bcbc70fb988958b1';

class ModelSpec {
  const ModelSpec({
    required this.id,
    required this.name,
    required this.fileName,
    required this.url,
    required this.sha256,
    required this.sizeBytes,
    required this.whisperModel,
    required this.quantization,
    required this.description,
  });

  final String id;
  final String name;
  final String fileName;
  final String url;
  final String sha256;
  final int sizeBytes;
  final WhisperModel whisperModel;
  final String quantization;
  final String description;
}

const List<ModelSpec> modelCatalog = [
  ModelSpec(
    id: 'whisper-tiny-q5_1',
    name: 'Whisper Tiny Q5_1',
    fileName: 'ggml-tiny-q5_1.bin',
    url: '$_whisperRepositoryUrl/ggml-tiny-q5_1.bin',
    sha256: '818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7',
    sizeBytes: 32152673,
    whisperModel: WhisperModel.tiny,
    quantization: 'Q5_1',
    description: '가장 가벼운 속도 기준 모델',
  ),
  ModelSpec(
    id: 'whisper-tiny-q8_0',
    name: 'Whisper Tiny Q8_0',
    fileName: 'ggml-tiny-q8_0.bin',
    url: '$_whisperRepositoryUrl/ggml-tiny-q8_0.bin',
    sha256: 'c2085835d3f50733e2ff6e4b41ae8a2b8d8110461e18821b09a15c40c42d1cca',
    sizeBytes: 43537433,
    whisperModel: WhisperModel.tiny,
    quantization: 'Q8_0',
    description: 'Tiny 고정밀 양자화 모델',
  ),
  ModelSpec(
    id: 'whisper-base-q5_1',
    name: 'Whisper Base Q5_1',
    fileName: 'ggml-base-q5_1.bin',
    url: '$_whisperRepositoryUrl/ggml-base-q5_1.bin',
    sha256: '422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898',
    sizeBytes: 59707625,
    whisperModel: WhisperModel.base,
    quantization: 'Q5_1',
    description: '속도와 품질의 기본 비교 모델',
  ),
  ModelSpec(
    id: 'whisper-base-q8_0',
    name: 'Whisper Base Q8_0',
    fileName: 'ggml-base-q8_0.bin',
    url: '$_whisperRepositoryUrl/ggml-base-q8_0.bin',
    sha256: 'c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9',
    sizeBytes: 81768585,
    whisperModel: WhisperModel.base,
    quantization: 'Q8_0',
    description: 'Base 고정밀 양자화 모델',
  ),
  ModelSpec(
    id: 'whisper-small-q5_1',
    name: 'Whisper Small Q5_1',
    fileName: 'ggml-small-q5_1.bin',
    url: '$_whisperRepositoryUrl/ggml-small-q5_1.bin',
    sha256: 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb',
    sizeBytes: 190085487,
    whisperModel: WhisperModel.small,
    quantization: 'Q5_1',
    description: '중급 모바일 기기 비교 모델',
  ),
  ModelSpec(
    id: 'whisper-small-q8_0',
    name: 'Whisper Small Q8_0',
    fileName: 'ggml-small-q8_0.bin',
    url: '$_whisperRepositoryUrl/ggml-small-q8_0.bin',
    sha256: '49c8fb02b65e6049d5fa6c04f81f53b867b5ec9540406812c643f177317f779f',
    sizeBytes: 264464607,
    whisperModel: WhisperModel.small,
    quantization: 'Q8_0',
    description: 'Small 고정밀 양자화 모델',
  ),
  ModelSpec(
    id: 'whisper-medium-q5_0',
    name: 'Whisper Medium Q5_0',
    fileName: 'ggml-medium-q5_0.bin',
    url: '$_whisperRepositoryUrl/ggml-medium-q5_0.bin',
    sha256: '19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f',
    sizeBytes: 539212467,
    whisperModel: WhisperModel.medium,
    quantization: 'Q5_0',
    description: '고사양 기기 권장',
  ),
  ModelSpec(
    id: 'whisper-medium-q8_0',
    name: 'Whisper Medium Q8_0',
    fileName: 'ggml-medium-q8_0.bin',
    url: '$_whisperRepositoryUrl/ggml-medium-q8_0.bin',
    sha256: '42a1ffcbe4167d224232443396968db4d02d4e8e87e213d3ee2e03095dea6502',
    sizeBytes: 823369779,
    whisperModel: WhisperModel.medium,
    quantization: 'Q8_0',
    description: '고사양 기기용 Medium 고정밀 모델',
  ),
  ModelSpec(
    id: 'whisper-large-v3-turbo-q5_0',
    name: 'Whisper Large V3 Turbo Q5_0',
    fileName: 'ggml-large-v3-turbo-q5_0.bin',
    url: '$_whisperRepositoryUrl/ggml-large-v3-turbo-q5_0.bin',
    sha256: '394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2',
    sizeBytes: 574041195,
    whisperModel: WhisperModel.large,
    quantization: 'Q5_0',
    description: '고품질·고속 Turbo, 고사양 기기 권장',
  ),
  ModelSpec(
    id: 'whisper-large-v3-turbo-q8_0',
    name: 'Whisper Large V3 Turbo Q8_0',
    fileName: 'ggml-large-v3-turbo-q8_0.bin',
    url: '$_whisperRepositoryUrl/ggml-large-v3-turbo-q8_0.bin',
    sha256: '317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1',
    sizeBytes: 874188075,
    whisperModel: WhisperModel.large,
    quantization: 'Q8_0',
    description: 'Turbo 고정밀 모델, 고사양 기기 권장',
  ),
  ModelSpec(
    id: 'whisper-large-v3-q5_0',
    name: 'Whisper Large V3 Q5_0',
    fileName: 'ggml-large-v3-q5_0.bin',
    url: '$_whisperRepositoryUrl/ggml-large-v3-q5_0.bin',
    sha256: 'd75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1',
    sizeBytes: 1081140203,
    whisperModel: WhisperModel.large,
    quantization: 'Q5_0',
    description: '최고 품질 비교용, 1GB 이상·고사양 기기 권장',
  ),
];

class DownloadedModel {
  const DownloadedModel({required this.spec, required this.file});

  final ModelSpec spec;
  final File file;
}

/// Audio containers/codecs accepted by the bundled FFmpeg mobile runtime.
/// Every input is normalized to 16 kHz, mono, signed 16-bit PCM WAV before
/// being passed to whisper.cpp.
const Set<String> supportedAudioExtensions = {
  '.wav',
  '.m4a',
  '.mp3',
  '.flac',
  '.ogg',
  '.opus',
  '.aac',
  '.mp4',
  '.webm',
  '.caf',
  '.aif',
  '.aiff',
  '.3gp',
  '.amr',
};

class AudioSample {
  const AudioSample({required this.assetPath, this.referenceAssetPath});

  final String assetPath;
  final String? referenceAssetPath;

  String get fileName => assetPath.split('/').last;
  String get extension => _fileExtension(fileName);
  bool get isWav => extension == '.wav';
}

class StagedAudio {
  const StagedAudio({
    required this.file,
    required this.stagingTime,
    this.audioDuration,
    this.reference,
  });

  final File file;
  final Duration stagingTime;
  final Duration? audioDuration;
  final String? reference;
}

class BenchmarkSegment {
  const BenchmarkSegment({
    required this.from,
    required this.to,
    required this.text,
  });

  final Duration from;
  final Duration to;
  final String text;
}

class BenchmarkResult {
  const BenchmarkResult({
    required this.sample,
    required this.transcript,
    required this.formattedTranscript,
    required this.transcriptSegments,
    required this.stagingTime,
    required this.processingTime,
    required this.model,
    required this.segments,
    this.audioDuration,
    this.reference,
  });

  final AudioSample sample;
  final String transcript;
  final String formattedTranscript;
  final List<BenchmarkSegment> transcriptSegments;
  final Duration stagingTime;
  final Duration processingTime;
  final Duration? audioDuration;
  final String? reference;
  final DownloadedModel model;
  final int segments;

  double? get rtf {
    final milliseconds = audioDuration?.inMilliseconds;
    if (milliseconds == null || milliseconds == 0) return null;
    return processingTime.inMilliseconds / milliseconds;
  }
}

class AssetDataset {
  Future<List<AudioSample>> loadSamples() async {
    final manifest = await AssetManifest.loadFromAssetBundle(rootBundle);
    final assets = manifest.listAssets().toSet();
    final audioAssets = assets.where((path) {
      final lower = path.toLowerCase();
      return path.startsWith('assets/data/') &&
          supportedAudioExtensions.any(lower.endsWith);
    }).toList()..sort();

    return audioAssets
        .map((audioPath) {
          String? referencePath;
          if (audioPath.contains('/kcsc/WAV/') && audioPath.endsWith('.wav')) {
            final candidate = audioPath
                .replaceFirst('/kcsc/WAV/', '/kcsc/TXT/')
                .replaceFirst(RegExp(r'\.wav$'), '.txt');
            if (assets.contains(candidate)) referencePath = candidate;
          }
          return AudioSample(
            assetPath: audioPath,
            referenceAssetPath: referencePath,
          );
        })
        .toList(growable: false);
  }

  Future<StagedAudio> stage(AudioSample sample) async {
    final stopwatch = Stopwatch()..start();
    final data = await rootBundle.load(sample.assetPath);
    final bytes = data.buffer.asUint8List(
      data.offsetInBytes,
      data.lengthInBytes,
    );
    final tempDirectory = await getTemporaryDirectory();
    final stageDirectory = Directory('${tempDirectory.path}/stt_mobile_bench');
    await stageDirectory.create(recursive: true);
    // Use a deterministic ASCII-only cache name. This avoids path parsing
    // issues in native audio libraries while the UI still shows fileName.
    final cacheKey = sha256.convert(utf8.encode(sample.assetPath)).toString();
    final file = File('${stageDirectory.path}/$cacheKey${sample.extension}');
    await file.writeAsBytes(bytes, flush: true);
    stopwatch.stop();

    String? reference;
    if (sample.referenceAssetPath case final referencePath?) {
      reference = (await rootBundle.loadString(referencePath)).trim();
    }

    return StagedAudio(
      file: file,
      stagingTime: stopwatch.elapsed,
      audioDuration: sample.isWav ? _wavDuration(data) : null,
      reference: reference,
    );
  }
}

class ModelRepository {
  Future<Directory> _modelDirectory() async {
    final root = await getApplicationSupportDirectory();
    final directory = Directory('${root.path}/models');
    await directory.create(recursive: true);
    return directory;
  }

  Future<File> modelFile(ModelSpec model) async {
    final directory = await _modelDirectory();
    return File('${directory.path}/${model.fileName}');
  }

  Future<File> _verificationFile(ModelSpec model) async {
    final file = await modelFile(model);
    return File('${file.path}.sha256');
  }

  Future<bool> isDownloaded(ModelSpec model) async {
    final file = await modelFile(model);
    if (!await file.exists() || await file.length() != model.sizeBytes) {
      return false;
    }

    final verification = await _verificationFile(model);
    if (await verification.exists() &&
        (await verification.readAsString()).trim() == model.sha256) {
      return true;
    }

    // Migrates models downloaded by an older app version and catches a
    // same-sized but corrupt file. The marker avoids hashing on every launch.
    if (await _sha256(file) != model.sha256) return false;
    await verification.writeAsString(model.sha256, flush: true);
    return true;
  }

  Future<List<DownloadedModel>> downloadedModels() async {
    final result = <DownloadedModel>[];
    for (final model in modelCatalog) {
      if (await isDownloaded(model)) {
        result.add(DownloadedModel(spec: model, file: await modelFile(model)));
      }
    }
    return result;
  }

  Future<File> downloadModel(
    ModelSpec model, {
    required void Function(double value) onProgress,
    required void Function(String status) onStatus,
  }) async {
    final target = await modelFile(model);
    if (await target.exists()) {
      onStatus('저장된 모델 검증 중');
      if (await isDownloaded(model)) {
        onProgress(1);
        return target;
      }
      await target.delete();
      final verification = await _verificationFile(model);
      if (await verification.exists()) await verification.delete();
    }

    final partial = File('${target.path}.part');
    if (await partial.exists()) await partial.delete();
    final client = HttpClient();
    IOSink? sink;
    try {
      onStatus('모델 다운로드 중');
      final uri = Uri.parse(model.url);
      final request = await client.getUrl(uri);
      final response = await request.close();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException(
          '모델 다운로드 실패: HTTP ${response.statusCode}',
          uri: uri,
        );
      }

      final total = response.contentLength;
      var received = 0;
      sink = partial.openWrite();
      await for (final chunk in response) {
        sink.add(chunk);
        received += chunk.length;
        if (total > 0) onProgress(received / total);
      }
      await sink.flush();
      await sink.close();
      sink = null;

      onStatus('다운로드 파일 검증 중');
      if (await partial.length() != model.sizeBytes) {
        throw FormatException(
          '모델 크기가 예상값과 다릅니다: '
          '${await partial.length()} / ${model.sizeBytes} bytes',
        );
      }
      final digest = await _sha256(partial);
      if (digest != model.sha256) {
        throw const FormatException('모델 SHA-256이 예상값과 다릅니다.');
      }
      await partial.rename(target.path);
      final verification = await _verificationFile(model);
      await verification.writeAsString(model.sha256, flush: true);
      onProgress(1);
      return target;
    } catch (_) {
      await sink?.close();
      if (await partial.exists()) await partial.delete();
      rethrow;
    } finally {
      client.close(force: true);
    }
  }

  Future<String> _sha256(File file) async {
    return (await sha256.bind(file.openRead()).first).toString();
  }

  Future<void> deleteModel(ModelSpec model) async {
    final file = await modelFile(model);
    final partial = File('${file.path}.part');
    final verification = await _verificationFile(model);
    if (await partial.exists()) await partial.delete();
    if (await verification.exists()) await verification.delete();
    if (await file.exists()) await file.delete();
  }
}

class WhisperBenchmarkEngine {
  Future<BenchmarkResult> run({
    required AudioSample sample,
    required DownloadedModel model,
    required int threads,
    required void Function(int value) onProgress,
    void Function()? onInferenceStarted,
  }) async {
    final staged = await AssetDataset().stage(sample);
    final stopwatch = Stopwatch()..start();
    onInferenceStarted?.call();
    try {
      final whisper = Whisper(model: model.spec.whisperModel);
      final response = await whisper.transcribe(
        transcribeRequest: TranscribeRequest(
          audio: staged.file.path,
          language: 'ko',
          threads: threads,
          isNoTimestamps: false,
          isRealtime: true,
        ),
        modelPath: model.file.path,
        onProgress: onProgress,
      );
      stopwatch.stop();
      final convertedFile = File('${staged.file.path}.wav');
      final audioDuration =
          staged.audioDuration ?? await _wavFileDuration(convertedFile);
      final transcriptSegments = (response.segments ?? const [])
          .map(
            (segment) => BenchmarkSegment(
              from: segment.fromTs,
              to: segment.toTs,
              text: segment.text.trim(),
            ),
          )
          .where((segment) => segment.text.isNotEmpty)
          .toList(growable: false);
      return BenchmarkResult(
        sample: sample,
        transcript: response.text.trim(),
        formattedTranscript: formatPredictionTranscript(
          segments: transcriptSegments,
          transcript: response.text,
          reference: staged.reference,
          audioDuration: audioDuration,
        ),
        transcriptSegments: transcriptSegments,
        reference: staged.reference,
        stagingTime: staged.stagingTime,
        processingTime: stopwatch.elapsed,
        audioDuration: audioDuration,
        model: model,
        segments: response.segments?.length ?? 0,
      );
    } finally {
      if (stopwatch.isRunning) stopwatch.stop();
      await _deleteIfPresent(staged.file);
      await _deleteIfPresent(File('${staged.file.path}.wav'));
    }
  }

  Future<void> _deleteIfPresent(File file) async {
    if (await file.exists()) await file.delete();
  }

  Future<Duration?> _wavFileDuration(File file) async {
    if (!await file.exists()) return null;
    final bytes = await file.readAsBytes();
    return _wavDuration(ByteData.sublistView(bytes));
  }
}

Duration? _wavDuration(ByteData bytes) {
  if (bytes.lengthInBytes < 44 ||
      _fourCc(bytes, 0) != 'RIFF' ||
      _fourCc(bytes, 8) != 'WAVE') {
    return null;
  }

  var offset = 12;
  int? byteRate;
  int? dataBytes;

  while (offset + 8 <= bytes.lengthInBytes) {
    final id = _fourCc(bytes, offset);
    final size = bytes.getUint32(offset + 4, Endian.little);
    final body = offset + 8;
    if (body + size > bytes.lengthInBytes) break;

    if (id == 'fmt ' && size >= 16) {
      byteRate = bytes.getUint32(body + 8, Endian.little);
    } else if (id == 'data') {
      dataBytes = size;
    }
    offset = body + size + (size.isOdd ? 1 : 0);
  }

  if (byteRate == null || byteRate == 0 || dataBytes == null) return null;
  return Duration(milliseconds: (dataBytes * 1000 / byteRate).round());
}

String _fourCc(ByteData bytes, int offset) {
  return String.fromCharCodes(
    List<int>.generate(4, (index) => bytes.getUint8(offset + index)),
  );
}

String _fileExtension(String path) {
  final slash = path.lastIndexOf('/');
  final dot = path.lastIndexOf('.');
  if (dot <= slash) return '';
  return path.substring(dot).toLowerCase();
}

String formatDuration(Duration duration) {
  final totalSeconds = duration.inMilliseconds / 1000;
  if (totalSeconds < 60) return '${totalSeconds.toStringAsFixed(2)}초';
  final minutes = duration.inMinutes;
  final seconds = duration.inSeconds.remainder(60);
  return '$minutes분 ${seconds.toString().padLeft(2, '0')}초';
}

String formatBytes(int bytes) {
  const megabyte = 1000 * 1000;
  if (bytes < megabyte) return '${(bytes / 1000).toStringAsFixed(1)} KB';
  return '${(bytes / megabyte).toStringAsFixed(1)} MB';
}

String compactReference(String value) {
  return const LineSplitter()
      .convert(value)
      .map((line) => line.trim())
      .where((line) => line.isNotEmpty)
      .join('\n');
}

String formatPredictionTranscript({
  required List<BenchmarkSegment> segments,
  required String transcript,
  String? reference,
  Duration? audioDuration,
}) {
  final metadata = _referenceMetadata(reference);
  final speakerId = metadata?.$1 ?? 'PRED';
  final gender = metadata?.$2 ?? 'unknown';
  final usableSegments = segments.where((segment) => segment.text.isNotEmpty);
  final rows = usableSegments
      .map(
        (segment) =>
            '[${_seconds(segment.from)},${_seconds(segment.to)}]\t'
            '$speakerId\t$gender\t${segment.text.trim()}',
      )
      .toList();

  if (rows.isEmpty && transcript.trim().isNotEmpty) {
    rows.add(
      '[0.000,${_seconds(audioDuration ?? Duration.zero)}]\t'
      '$speakerId\t$gender\t${transcript.trim()}',
    );
  }
  return rows.isEmpty ? '(출력 없음)' : rows.join('\n');
}

(String, String)? _referenceMetadata(String? reference) {
  if (reference == null) return null;
  for (final line in const LineSplitter().convert(reference)) {
    final columns = line.split('\t');
    if (columns.length >= 4) return (columns[1].trim(), columns[2].trim());
  }
  return null;
}

String _seconds(Duration duration) {
  return (duration.inMicroseconds / Duration.microsecondsPerSecond)
      .toStringAsFixed(3);
}
