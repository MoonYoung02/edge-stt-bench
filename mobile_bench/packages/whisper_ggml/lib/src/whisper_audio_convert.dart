import 'dart:async';

import 'package:ffmpeg_kit_flutter_new_min/ffmpeg_kit.dart';
import 'package:ffmpeg_kit_flutter_new_min/ffmpeg_session.dart';
import 'package:ffmpeg_kit_flutter_new_min/return_code.dart';
import 'package:flutter/foundation.dart';
import 'package:universal_io/io.dart';

/// Class used to convert any audio file to wav
class WhisperAudioConvert {
  ///
  const WhisperAudioConvert({
    required this.audioInput,
    required this.audioOutput,
  });

  /// Input audio file
  final File audioInput;

  /// Output audio file
  /// Overwriten if already exist
  final File audioOutput;

  /// convert [audioInput] to wav file
  Future<File?> convert() async {
    if (Platform.isWindows || Platform.isLinux) {
      return _convertWithFfmpegCli();
    }

    // Pass arguments directly instead of building a shell-like command.
    // FFmpegKit.execute() reparses a String on spaces, which breaks valid
    // Paths may contain Unicode characters, such as "테스트 녹음본.m4a".
    final FFmpegSession session = await FFmpegKit.executeWithArguments([
      '-y',
      '-i',
      audioInput.path,
      '-vn',
      '-ar',
      '16000',
      '-ac',
      '1',
      '-c:a',
      'pcm_s16le',
      audioOutput.path,
    ]);

    final ReturnCode? returnCode = await session.getReturnCode();

    if (ReturnCode.isSuccess(returnCode)) {
      return audioOutput;
    } else if (ReturnCode.isCancel(returnCode)) {
      throw StateError('오디오 변환이 취소되었습니다.');
    } else {
      final String details = (await session.getOutput())?.trim() ?? '';
      debugPrint(
        'Audio conversion failed with returnCode ${returnCode?.getValue()}: '
        '$details',
      );
      throw FormatException(
        '지원하지 않거나 손상된 오디오 파일입니다 '
        '(FFmpeg code ${returnCode?.getValue()}).',
      );
    }
  }

  /// ffmpeg_kit has no Windows or Linux implementation, so those platforms
  /// use an `ffmpeg` executable from PATH instead. Returns null when ffmpeg
  /// is missing or fails; callers then transcribe the original file, which
  /// works as long as it is already a 16 kHz mono WAV.
  Future<File?> _convertWithFfmpegCli() async {
    try {
      final ProcessResult result = await Process.run('ffmpeg', [
        '-y',
        '-i',
        audioInput.path,
        '-ar',
        '16000',
        '-ac',
        '1',
        '-c:a',
        'pcm_s16le',
        audioOutput.path,
      ]);
      if (result.exitCode == 0) {
        return audioOutput;
      }
      debugPrint(
        'File convertion error with exitCode ${result.exitCode}: '
        '${result.stderr}',
      );
    } on ProcessException {
      debugPrint(
        'ffmpeg not found on PATH; passing audio through unconverted. '
        'Input must be a 16 kHz mono WAV.',
      );
    }
    return null;
  }
}
