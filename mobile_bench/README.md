# EdgeSTT Mobile Bench

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
- 내장 오디오 한 개를 선택하는 수동 실행
- 정답 TXT가 있는 KCSC 샘플 전체를 한 모델로 순차 실행하는 자동 벤치마크
- 같은 모델·샘플의 완료 결과 재사용과 자동 벤치마크 이력 조회
- CPU thread 수 선택
- 모델 관리 화면에서 다국어 Whisper 모델 12종(문맥 전달을 끈 no-context A/B
  실험 변형 포함)과 Sherpa-ONNX 모델 2종을 개별 다운로드·검증·삭제
- SHA-256 검증이 끝난 모델만 벤치마크 화면에서 선택
- Android 네이티브 `whisper.cpp`와 `sherpa-onnx` 두 엔진으로 추론
- 실행 완료 즉시 정답 TXT 유무와 무관하게 별도 결과 화면 표시
- 전체 처리 시간, RTF, segment 수와 timestamp 기반 transcript 표시
- KCSC sample은 대응하는 정답 TXT도 함께 표시
- 실행 중 앱 CPU, RAM, 발열 상태와 배터리 온도를 500ms 간격으로 표시·기록
- 실행 결과 이력, CPU/RAM/thermal 그래프와 JSON 영구 저장
- 등록한 HTTPS 서버로 결과 JSON 전송(Bearer token은 secure storage에 보관)
- Android Downloads 내보내기와 ADB pull
- Android foreground service + partial wake lock으로 화면 꺼짐/앱 화면 이탈 중 실행
- 샘플별 발열 상태 기록과 실패 후 다음 샘플 계속 실행

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

정답이 있는 KCSC 전체를 측정하려면 홈 화면의 `자동 벤치마크`를 엽니다. 모델과
thread 수를 고르면 22개 샘플을 차례대로 실행합니다. 동일한 모델로 이미 완료한
샘플은 기존 결과를 재사용하고 나머지만 실행하므로, 중단된 측정을 보충하거나 새
샘플을 추가한 뒤 다시 실행하기 쉽습니다. 한 샘플이 실패해도 다음 샘플은 계속
실행되며, 실행 직전 발열 상태가 높은 샘플은 결과에 표시됩니다. 진행 중인 자동
벤치마크는 취소할 수 있고, 완료된 배치는 `자동 벤치마크 이력`에서 다시 확인할 수
있습니다.

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
| Whisper Small Q8_0 (no-context 실험) | 264.5MB (Small Q8_0과 같은 파일) |
| Whisper Medium Q5_0 | 539.2MB |
| Whisper Medium Q8_0 | 823.4MB |
| Whisper Large V3 Turbo Q5_0 | 574.0MB |
| Whisper Large V3 Turbo Q8_0 | 874.2MB |
| Whisper Large V3 Q5_0 | 1,081.1MB |
| Sherpa-ONNX 한국어 스트리밍 Zipformer | 418.2MB (압축 해제 후 encoder+decoder+joiner ≈132MB) |
| Sherpa-ONNX SenseVoice Small (int8) | 163.0MB (압축 해제 후 ≈229MB) |

500MB 이상 모델은 다운로드 전에 저장공간과 RAM 안내를 표시합니다. 모두 한국어를
지원하는 다국어 모델이며 영어 전용 `.en` 모델은 현재 카탈로그에서 제외했습니다.
크기는 전부 다운로드하는 파일 자체의 크기이고, Sherpa-ONNX 두 모델만 압축
해제 후 실제 사용하는 파일 크기가 따로 있어 괄호로 병기했습니다.

Whisper 계열은 `whisper.cpp`(GGML, 단일 파일) 엔진으로, Sherpa-ONNX 두 모델은
`sherpa-onnx`(ONNX Runtime, `.tar.bz2`로 배포되어 앱이 내부에서 압축 해제) 엔진으로
실행됩니다. 한국어 스트리밍 Zipformer는 오디오를 100ms 청크로 나눠 넣는 실시간
스트리밍 방식으로, SenseVoice는 파일 전체를 한 번에 넣는 오프라인 방식으로
동작합니다. 두 sherpa-onnx 모델 모두 현재는 16kHz mono 16-bit PCM WAV 입력만
지원합니다(KCSC 샘플은 전부 이 형식). 다른 포맷/샘플레이트 입력은 아직
whisper.cpp처럼 FFmpeg로 자동 정규화되지 않고 오류로 표시됩니다.

`Whisper Small Q8_0 (no-context 실험)`은 별도 다운로드가 아니라 Small Q8_0과
같은 GGML 파일을 공유하는 디코딩 옵션 변형입니다. whisper.cpp는 기본적으로
직전 구간의 전사를 다음 구간 디코딩의 문맥으로 넘기는데, KCSC 오디오는 서로
무관한 발화를 이어붙인 파일이라 이 문맥이 반복·환각(같은 문장을 계속
되풀이하는 현상)을 유발하는 경우가 있습니다. 이 항목은 문맥 전달을 끄고 같은
모델을 다시 실행해 그 영향을 A/B로 비교하기 위한 것입니다.

현재 `data/` 전체를 포함한 ARM64 release APK 크기는 약 710MB입니다.

실행 중에는 상단 카드에서 CPU/RAM/발열을 확인할 수 있습니다. 완료된 실행은
`결과 이력`에 JSON으로 남고 결과 화면에서 그래프, 서버 전송과 파일 내보내기를
사용할 수 있습니다. Android USB 수집은 다음과 같습니다.

```bash
./tools/pull_benchmark_results.sh R3CRC0LMBTJ ./benchmark-results
```

디버그 APK에서는 앱 내부 결과를 바로 가져오며, release APK에서는 결과 화면의
내보내기를 먼저 누르면 Downloads 폴더에서 가져옵니다. 결과가 많이 쌓였을 때
최근 것만 가져오려면 `--recent N`을 앞에 붙입니다(기기 쪽 수정 시각 기준 최신
N개).

```bash
./tools/pull_benchmark_results.sh --recent 5 R3CRC0LMBTJ ./benchmark-results
```

기기 시리얼을 생략하면(빈 문자열 `""`) 연결된 첫 번째 기기를 자동으로 씁니다.
`watch_benchmark_results.sh`도 동일한 인자를 그대로 받습니다.

### 모바일 결과 채점과 변환

가져온 자동 벤치마크 JSON의 CER/WER와 RTF 요약만 만들려면 다음 명령을
사용합니다. 같은 `runId`의 파일이 여러 번 내보내졌다면 첫 번째 파일만 사용합니다.

```bash
python3 tools/mobile_result_importer.py ./benchmark-results \
  --output ./benchmark-results/scored
```

모바일 결과를 데스크톱 `sttbench`의 `runs/`와 같은 구조로 변환하려면 다음 명령을
사용합니다. 배치 자동 실행이든 수동 단일 실행이든 파일 하나마다 각각 독립된 실행
폴더가 됩니다(`batchId`로 묶지 않습니다). 어느 배치에서 나온 샘플인지는 각 실행의
`run.json`의 `mobile_source.batch_id`에 그대로 남습니다.

```bash
python3 tools/mobile_to_runs.py ./benchmark-results \
  --runs-dir ../runs
```

`./benchmark-results`에 예전 실행까지 계속 쌓여 있어 방금 가져온 것만 변환하고
싶다면 `--recent N`으로 파일 수정 시각 기준 최신 N개만 골라 변환합니다. 파일마다
독립된 실행 폴더가 되므로 배치 일부만 골라도 "일부가 빠진 실행"이 생기지 않습니다.

```bash
python3 tools/mobile_to_runs.py ./benchmark-results --recent 5 --runs-dir ../runs
```

두 도구 모두 데스크톱과 동일한 텍스트 정규화 및 CER/WER 구현을 재사용합니다.
`mobile_result_importer.py`는 빠른 배치 요약용이고, `mobile_to_runs.py`는 샘플별
`prediction.json`, `comparison.json`, `summary.json`까지 만들어 데스크톱 결과와
나란히 비교할 때 사용합니다.

`mobile_to_runs.py`가 파일마다 독립된 실행 폴더를 만들기 때문에, 같은 모델을 여러
번(또는 여러 세션에 걸쳐) 돌린 결과를 하나의 요약으로 다시 합치려면
`summarize_recent_runs.py`를 사용합니다. 각 실행의 `run.json`에 적힌 `started_at`
기준으로 가장 최근 N개를 골라 데스크톱과 동일한 `# KCSC ASR 평가 요약` 형식의
markdown 하나로 합칩니다.

```bash
python3 tools/summarize_recent_runs.py --recent 15
# 특정 모델만: --model whisper-small-q8_0-no-context
# 저장 경로 지정: --output ./benchmark-results/recent-15-summary.md
```

`--runs-dir`를 생략하면 `mobile_bench/benchmark-results/runs`를 보고, `--output`을
생략하면 `benchmark-results/recent-<N>[-<모델>]-summary.md`에 저장하면서 화면에도
그대로 출력합니다. `--model`을 생략하면 폴더 안의 모든 모델을 다 합치므로, 여러
모델이 섞여 있을 때는 `--model`로 좁히는 걸 권장합니다.

### Mac 로컬 서버로 바로 업로드

추가 패키지 없이 Python 수신 서버를 실행할 수 있습니다.

```bash
cd mobile_bench
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

아키텍처 문서의 `jobId`/Firebase Test Lab 무인 실행과 벤치마크 규약 문서의
warmup·반복 측정·cold/warm 분리 스키마는 목표로 삼은 설계이고, 아래 "현재
제한"에 있듯 아직 구현되지 않았습니다. 지금 앱은 샘플당 1회만 측정합니다.

## 프로젝트 구조

현재 주요 구성은 다음과 같습니다.

```text
mobile_bench/
├── README.md
├── docs/
├── lib/
│   ├── main.dart
│   └── src/
│       ├── benchmark_home_page.dart          # 수동 실행 홈
│       ├── benchmark_batch_page.dart         # 자동 실행 화면과 진행 상태
│       ├── benchmark_batch_history_page.dart # 완료된 배치 이력
│       ├── benchmark_history_page.dart       # 단일 실행 이력
│       ├── benchmark_result_page.dart        # 결과 화면(그래프·내보내기·업로드)
│       ├── benchmark_coordinator.dart        # 단일/배치 실행 조율, 화면 wakelock
│       ├── benchmark_services.dart           # 모델 카탈로그·whisper.cpp 엔진
│       ├── benchmark_run.dart                # 단일 실행/telemetry 데이터 모델
│       ├── benchmark_batch.dart              # 배치 실행 데이터 모델
│       ├── sherpa_engine.dart                # sherpa-onnx 엔진(스트리밍/오프라인)
│       ├── model_manager_page.dart           # 모델 다운로드·검증·삭제 화면
│       ├── server_manager_page.dart          # 업로드 서버 등록 화면
│       ├── server_services.dart              # 서버 프로필 저장, 업로드 요청
│       ├── telemetry_sampler.dart            # 500ms CPU/RAM/발열 폴링
│       ├── telemetry_chart.dart              # CPU/RAM/발열 그래프 위젯
│       ├── platform_bridge.dart              # 기기 정보·foreground service 연동
│       └── result_repository.dart            # 실행·배치 JSON 저장/조회
├── packages/
│   └── whisper_ggml/           # 로컬로 고정한 whisper.cpp Flutter 플러그인
├── assets/
│   └── data -> ../../data      # 원본 data/를 가리키는 asset 링크
├── tools/                       # 결과 수집·채점·변환 도구
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
- 수동 단일 실행과 정답이 있는 전체 샘플 자동 실행을 지원합니다. 임의 샘플 집합,
  duration 기반 shard, warmup/반복 횟수 지정과 `jobId` 기반 무인 실행은 아직
  지원하지 않습니다.
- 표시되는 `전체 처리`에는 플러그인 내부 WAV 준비와 모델 로딩이 포함됩니다.
- cold/warm 구간과 에너지 소비량은 아직 분리 측정하지 않습니다.
- 데이터셋은 아직 명시적인 버전/hash manifest 대신 Flutter `AssetManifest`에서
  파일을 찾습니다.
- 지원 목록 밖의 특수 codec이나 손상된 파일은 FFmpeg 변환 오류로 표시됩니다.
- Android 설정에서 앱을 강제 중지하거나 Android 13+ Active apps의 `Stop`을 누르면
  OS 정책상 실행을 계속할 수 없습니다.
- 모바일 앱은 Android만 지원합니다.

## 장기 MVP 완료 조건과 현재 상태

첫 번째 MVP는 다음 조건을 만족해야 합니다.

1. 완료 — Android에서 `whisper.cpp` GGML과 sherpa-onnx 모델을 로드합니다.
2. 부분 완료 — 단일 sample과 정답이 있는 전체 sample을 실행하며 shard는 남아
   있습니다.
3. 완료 — 모델을 URL에서 다운로드하고 크기와 SHA-256을 검증합니다.
4. 부분 완료 — 전체 처리 시간, RTF, CPU/RAM/thermal을 기록하며 cold/warm 및
   세부 측정 경계 분리는 남아 있습니다.
5. 완료 — transcript, 모델·기기·런타임 정보와 telemetry를 JSON으로 저장합니다.
6. 완료 — Android 실제 기기에서 수동 실행과 앱 내 자동 순차 실행이 가능합니다.
7. 미완료 — Firebase Test Lab의 `jobId` 기반 무인 실행이 남아 있습니다.
8. 완료 — 결과 importer와 변환기가 기존 `sttbench` 구현으로 CER/WER를 계산합니다.
