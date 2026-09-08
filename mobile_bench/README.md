# STT Mobile Benchmark App

Android 실제 기기에서 로컬 STT 모델의 속도, 메모리 사용량, 안정성을
반복 측정하기 위한 Flutter 앱 프로젝트입니다.

이 디렉터리는 앞으로 Flutter 애플리케이션, 네이티브 STT 엔진 바인딩,
Firebase Test Lab 실행 코드와 모바일 벤치마크 문서를 함께 관리하는 루트로
사용합니다.

## 현재 MVP 상태

빠르게 실제 기기에서 실행할 수 있는 첫 버전이 구현되어 있습니다.

- 저장소 `data/`의 음성 23개와 KCSC 정답 TXT 22개를 앱 asset으로 포함
- WAV, M4A, MP3, FLAC, OGG/OPUS, AAC, MP4, WebM 등 일반적인 오디오 입력을
  FFmpeg로 16 kHz mono PCM WAV로 정규화
- 내장 오디오 한 개 선택
- CPU thread 수 선택
- 모델 관리 화면에서 다국어 Whisper 모델 11종을 개별 다운로드·검증·삭제
- SHA-256 검증이 끝난 모델만 벤치마크 화면에서 선택
- Android 네이티브 `whisper.cpp` 추론
- 실행 완료 즉시 정답 TXT 유무와 무관하게 별도 결과 화면 표시
- 전체 처리 시간, RTF, segment 수와 timestamp 기반 transcript 표시
- KCSC sample은 대응하는 정답 TXT도 함께 표시
- 실행 중 앱 CPU, RAM, 발열 상태와 배터리 온도를 500ms 간격으로 표시·기록
- 실행 결과 이력, CPU/RAM/thermal 그래프와 JSON 영구 저장
- 등록한 HTTPS 서버로 결과 JSON 전송(Bearer token은 secure storage에 보관)
- Android Downloads 내보내기와 ADB pull
- Android foreground service + partial wake lock으로 화면 꺼짐/앱 화면 이탈 중 실행

현재 MVP는 `whisper_ggml` 2.6.0 소스를 `packages/whisper_ggml/`에 포함해
사용합니다. upstream Android 설정의 compileSdk 충돌을 피하기 위해 로컬 패키지는
compileSdk 36과 NDK 29로 고정했습니다.

## 빠른 실행

Android 실제 기기를 연결한 뒤 release 모드로 실행합니다.

```bash
cd mobile_bench
flutter pub get
flutter run --release
```

이미 생성된 ARM64 release APK는 다음 위치에 있습니다.

```text
build/app/outputs/flutter-apk/app-release.apk
```

앱 상단의 `모델 관리`에서 사용할 모델을 먼저 다운로드합니다. 벤치마크 화면으로
돌아오면 다운로드가 완료된 모델만 선택 목록에 나타납니다. 모델, 오디오와 thread
수를 고른 뒤 `벤치마크 시작`을 누르면 됩니다. 검증된 모델은 앱 내부 저장소에서
재사용합니다.

모델 출력은 정답 데이터와 동일한 4열 형식으로 표시합니다.

```text
[시작초,종료초]    화자ID    성별    문장
```

KCSC 정답이 있으면 해당 화자ID와 성별을 사용하고, 정답이 없는 일반 녹음은
`PRED`, `unknown`을 사용합니다. 정답 파일이 없는 경우에도 성능 지표와 모델 출력은
항상 표시됩니다.

현재 모델 카탈로그는 다음과 같습니다.

| 모델 | 파일 크기 |
|---|---:|
| Whisper Tiny Q5_1 | 32.2MB |
| Whisper Tiny Q8_0 | 43.5MB |
| Whisper Base Q5_1 | 59.7MB |
| Whisper Base Q8_0 | 81.8MB |
| Whisper Small Q5_1 | 190.1MB |
| Whisper Small Q8_0 | 264.5MB |
| Whisper Medium Q5_0 | 539.2MB |
| Whisper Medium Q8_0 | 823.4MB |
| Whisper Large V3 Turbo Q5_0 | 574.0MB |
| Whisper Large V3 Turbo Q8_0 | 874.2MB |
| Whisper Large V3 Q5_0 | 1,081.1MB |
| Sherpa-ONNX 한국어 스트리밍 Zipformer | 132.4MB |
| Sherpa-ONNX SenseVoice Small (int8) | 229.5MB |

500MB 이상 모델은 다운로드 전에 저장공간과 RAM 안내를 표시합니다. 모두 한국어를
지원하는 다국어 모델이며 영어 전용 `.en` 모델은 현재 카탈로그에서 제외했습니다.

Whisper 계열은 `whisper.cpp`(GGML, 단일 파일) 엔진으로, Sherpa-ONNX 두 모델은
`sherpa-onnx`(ONNX Runtime, `.tar.bz2`로 배포되어 앱이 내부에서 압축 해제) 엔진으로
실행됩니다. 한국어 스트리밍 Zipformer는 오디오를 100ms 청크로 나눠 넣는 실시간
스트리밍 방식으로, SenseVoice는 파일 전체를 한 번에 넣는 오프라인 방식으로
동작합니다. 두 sherpa-onnx 모델 모두 현재는 16kHz mono 16-bit PCM WAV 입력만
지원합니다(KCSC 샘플은 전부 이 형식). 다른 포맷/샘플레이트 입력은 아직
whisper.cpp처럼 FFmpeg로 자동 정규화되지 않고 오류로 표시됩니다.

현재 `data/` 전체를 포함한 ARM64 release APK 크기는 약 710MB입니다.

실행 중에는 상단 카드에서 CPU/RAM/발열을 확인할 수 있습니다. 완료된 실행은
`결과 이력`에 JSON으로 남고 결과 화면에서 그래프, 서버 전송과 파일 내보내기를
사용할 수 있습니다. Android USB 수집은 다음과 같습니다.

```bash
./tools/pull_benchmark_results.sh R3CRC0LMBTJ ./benchmark-results
```

디버그 APK에서는 앱 내부 결과를 바로 가져오며, release APK에서는 결과 화면의
내보내기를 먼저 누르면 Downloads 폴더에서 가져옵니다.

### Mac 로컬 서버로 바로 업로드

추가 패키지 없이 Python 수신 서버를 실행할 수 있습니다.

```bash
cd /Users/moonyoung/whisper/mobile_bench
./tools/result_receiver.py --port 8787 --output ./received-benchmark-results
```

휴대폰과 Mac이 같은 Wi-Fi라면 앱 `서버 관리`에 Mac의 사설 IP를 등록합니다.

```text
이름: Mac local
Base URL: http://192.168.0.5:8787
Endpoint: /api/v1/benchmark-runs
Bearer token: 비워 둠
```

USB 디버깅 연결을 이용하려면 Mac에서 먼저 포트를 연결합니다.

```bash
adb reverse tcp:8787 tcp:8787
```

이 경우 앱의 Base URL은 `http://127.0.0.1:8787`입니다. 결과 화면에서 서버를
선택하고 업로드 버튼을 누르면 `received-benchmark-results/<runId>.json`으로
저장됩니다. 일반 인터넷 서버에는 계속 HTTPS를 사용해야 하며, HTTP는 사설망과
ADB 로컬 주소에만 허용합니다.

## 현재 확정된 방향

- Flutter는 UI와 벤치마크 작업 오케스트레이션을 담당합니다.
- 실제 STT 추론은 `whisper.cpp` 등의 네이티브 런타임이 수행합니다.
- Flutter와 C/C++ 런타임은 Dart FFI로 연결합니다.
- 모델은 APK/앱 번들에 포함하지 않고 실행 시 원격 저장소에서 다운로드합니다.
- 저장소 루트의 `data/` 전체는 빌드 시 앱 asset에 포함합니다.
- 모델 다운로드와 asset 준비 시간은 STT 추론 시간에서 제외합니다.
- 하나의 앱 빌드를 유지하고 런타임 `jobId`로 모델과 실행 조건을 선택합니다.
- 모든 실행은 모델, 데이터셋, 런타임과 기기 정보를 포함한 JSON을 생성합니다.
- 시스템 계측은 500ms 간격으로 저장하고 화면 상태 변화도 함께 기록합니다.
- 장시간 실행은 플랫폼이 제공하는 사용자 인지형 백그라운드 API만 사용합니다.
- CER/WER는 모바일에서 별도로 구현하지 않고 기존 Python `sttbench`가 동일한
  규칙으로 계산합니다.

## 문서

- [아키텍처](docs/ARCHITECTURE.md): 앱 구성요소, 실행 상태, FFI와 Test Lab 연동
- [데이터셋](docs/DATASET.md): `data/` 패키징, manifest, asset staging과 shard 규칙
- [벤치마크 규약](docs/BENCHMARK_PROTOCOL.md): 측정 경계, 반복 조건, 지표와 결과 스키마
- [백그라운드·계측·전송](docs/BACKGROUND_MONITORING_AND_TRANSFER.md): 플랫폼 동작, 지표 정의, 서버/USB 사용법

## 프로젝트 구조

Flutter 프로젝트를 생성하면 이 디렉터리를 다음과 같이 확장합니다.

```text
mobile_bench/
├── README.md
├── docs/
├── lib/
│   ├── main.dart
│   └── src/
│       ├── benchmark_home_page.dart
│       └── benchmark_services.dart
├── packages/
│   └── whisper_ggml/           # 로컬로 고정한 whisper.cpp Flutter 플러그인
├── assets/
│   └── data -> ../../data      # 원본 data/를 가리키는 asset 링크
├── test/
├── android/                    # 유일한 모바일 대상 플랫폼
└── pubspec.yaml
```

`mobile_bench/assets/data/`는 저장소 루트 `data/`를 가리키는 상대 symlink입니다.
데이터를 중복 저장하지 않으면서 Flutter 빌드에는 전체 파일이 포함됩니다.

## 현재 제한

- 모델 카탈로그는 whisper.cpp GGML 다국어 모델과 sherpa-onnx 한국어 스트리밍
  Zipformer/SenseVoice int8 두 종으로 구성됩니다. sherpa-onnx 두 모델은 현재
  16kHz mono WAV 입력만 지원합니다.
- 1회 실행만 지원하며 batch/shard와 자동 Job 실행은 아직 없습니다.
- 표시되는 `전체 처리`에는 플러그인 내부 WAV 준비와 모델 로딩이 포함됩니다.
- cold/warm 구간과 에너지 소비량은 아직 분리 측정하지 않습니다.
- 지원 목록 밖의 특수 codec이나 손상된 파일은 FFmpeg 변환 오류로 표시됩니다.
- Android 설정에서 앱을 강제 중지하거나 Android 13+ Active apps의 `Stop`을 누르면
  OS 정책상 실행을 계속할 수 없습니다.
- 모바일 앱은 Android만 지원합니다.

## 장기 MVP 완료 조건

첫 번째 MVP는 다음 조건을 만족해야 합니다.

1. Android 앱에서 `whisper.cpp` GGML 모델을 로드할 수 있다.
2. `data/`에 포함된 지원 오디오 중 지정된 sample 또는 shard를 실행할 수 있다.
3. 모델은 URL에서 다운로드하고 SHA-256을 검증한다.
4. 모델 로딩 시간, 전처리 시간, 추론 시간, RTF와 Peak RAM을 기록한다.
5. transcript와 재현 정보를 결과 JSON으로 저장한다.
6. Android 실제 기기에서 수동 실행과 자동 실행이 모두 가능하다.
7. Firebase Test Lab에서 `jobId`를 전달해 UI 조작 없이 실행할 수 있다.
8. 생성된 모바일 결과를 기존 `sttbench`에서 읽고 CER/WER를 계산할 수 있다.

## 구현 순서

1. Android Flutter 프로젝트 생성
2. 네이티브 엔진 연결
3. asset 목록과 선택 파일 staging 구현
4. 단일 WAV/단일 GGML 모델 수동 벤치마크 구현
5. 메모리 및 기기 정보 수집 구현
6. 결과 JSON 저장과 기존 `sttbench` importer 구현
7. Android Firebase Test Lab 자동 실행 연결
8. 모델 및 STT 엔진 확장
