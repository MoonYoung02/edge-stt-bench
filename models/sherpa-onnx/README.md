# sherpa-onnx 모델 (모바일 벤치마크용)

`mobile_bench`에 whisper.cpp 외 엔진으로 추가할 sherpa-onnx 모델 2종의
확보 기록입니다. 앱 코드(`mobile_bench/lib/...`)는 아직 이 모델들을 쓰도록
연결되지 않았습니다 — 이 문서는 연결 작업을 다시 시작할 때 바로 쓸 수 있는
카탈로그 스펙입니다.

## 1. 한국어 스트리밍 Zipformer

- 용도: 실시간 자막/대화 인식 (streaming)
- 원본: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-korean-2024-06-16.tar.bz2
- 아카이브 크기: 418,218,652 bytes
- 아카이브 SHA-256: `e346a5882a409650472be17326237e24df7bf409db6b4a8a52e1a61422bf2500`

모바일에서 실제로 로드할 파일(int8, 총 ≈132.4MB):

| 파일 | 크기(bytes) | SHA-256 |
|---|---:|---|
| encoder-epoch-99-avg-1.int8.onnx | 126,968,852 | `8d0b1aa24fbedd4e3948564ab7facd151b8ce9b0c48fc987c541de2de3af5697` |
| decoder-epoch-99-avg-1.int8.onnx | 2,844,692 | `68ea197936aabd249f38b53a87c775422bca64428ad4427d0e6e8092593e71fb` |
| joiner-epoch-99-avg-1.int8.onnx | 2,581,421 | `128b80a66a1f718488af8560f9d15895109b99ff3e573f0a0130e03774ef1ced` |
| tokens.txt | 60,246 | `016bdf0965029263b7ad01b742366ee542ef0bef38261510e8176ff6f2e9e668` |

fp32 버전(encoder/decoder/joiner, sha256 미기록 필요 시 재계산)도 같은 디렉터리에
있으나 모바일 카탈로그에는 올리지 않을 예정. `test_wavs/0~3.wav` + `trans.txt`에
정답 스크립트 4개가 있어 엔진 연결 후 스모크 테스트로 바로 사용 가능.

sherpa_onnx Dart API 사용 형태(k2-fsa/sherpa-onnx `flutter-examples/streaming_asr`
기준):

```dart
sherpa_onnx.OnlineRecognizerConfig(
  model: sherpa_onnx.OnlineModelConfig(
    transducer: sherpa_onnx.OnlineTransducerModelConfig(
      encoder: '.../encoder-epoch-99-avg-1.int8.onnx',
      decoder: '.../decoder-epoch-99-avg-1.int8.onnx',
      joiner: '.../joiner-epoch-99-avg-1.int8.onnx',
    ),
    tokens: '.../tokens.txt',
    modelType: 'zipformer',
  ),
);
```

## 2. SenseVoiceSmall int8 (zh/en/ja/ko/yue)

- 용도: 녹음 종료 후 오프라인(배치) 전사
- 원본: https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
  (Hugging Face `csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`의
  `model.int8.onnx`/`tokens.txt`와 SHA-256이 완전히 동일함을 확인함 — 어느 쪽에서
  받아도 같은 파일)
- 아카이브 크기: 163,002,883 bytes
- 아카이브 SHA-256: `7d1efa2138a65b0b488df37f8b89e3d91a60676e416f515b952358d83dfd347e`

모바일에서 실제로 로드할 파일(총 ≈228.5MB):

| 파일 | 크기(bytes) | SHA-256 |
|---|---:|---|
| model.int8.onnx | 239,233,841 | `c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51` |
| tokens.txt | 315,894 | `f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc` |

`test_wavs/ko.wav`(+ zh/en/ja/yue)로 스모크 테스트 가능.

```dart
sherpa_onnx.OfflineRecognizerConfig(
  model: sherpa_onnx.OfflineModelConfig(
    senseVoice: sherpa_onnx.OfflineSenseVoiceModelConfig(
      model: '.../model.int8.onnx',
      language: 'auto', // 또는 'ko' 고정
      useInverseTextNormalization: false,
    ),
    tokens: '.../tokens.txt',
  ),
);
```

## 3. Flutter 패키지

두 모델 다 whisper_ggml처럼 벤더링할 필요 없이 공식 배포 패키지를 그대로 씀:

```yaml
dependencies:
  sherpa_onnx: ^1.13.7   # pub.dev, 확인일 기준 최신. Android arm64-v8a 포함 prebuilt 제공
  archive: ^4.2.0        # 다운로드한 .tar.bz2를 폰 안에서 순수 Dart로 압축 해제하는 데 사용
```

## 4. 남은 통합 작업 (아직 앱 코드에 반영 안 됨)

1. `ModelSpec`에 엔진 구분 필드 추가 (whisper_cpp 단일파일 vs sherpa-onnx 아카이브)
2. `ModelRepository.downloadModel()`이 검증 후 아카이브를 앱 저장소에 압축 해제하는
   단계 추가 (`archive` 패키지의 `BZip2Decoder` + `TarDecoder`)
3. `SherpaOnnxEngine` 작성 — 기존 `WhisperBenchmarkEngine.run()`과 동일하게
   `BenchmarkResult`를 반환하도록 만들어서 UI/저장/전송 코드는 그대로 재사용
   - 스트리밍(Zipformer): PCM을 청크로 나눠 `OnlineStream.acceptWaveform` 반복 호출
   - 오프라인(SenseVoice): `OfflineStream`에 전체 파형을 한 번에 넣고 decode
4. 모델 카탈로그에 위 두 엔트리 추가, 벤치마크 화면에서 엔진별 분기
5. (선택) 스트리밍 전용 지표(첫 partial까지 시간 등) `BenchmarkResult`에 추가

`mobile_bench`가 지금 다른 세션에서 batch 실행 기능으로 활발히 바뀌고 있어서
(2026-09-08 저녁), 그 작업이 끝난 뒤 위 4단계를 이어서 진행하기로 함.
