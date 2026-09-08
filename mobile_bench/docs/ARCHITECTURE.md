# 모바일 벤치마크 앱 아키텍처

## 1. 목적

이 앱의 목적은 동일한 모델 artifact와 동일한 오디오를 여러 Android 실제
기기에서 실행해 재현 가능한 성능 결과를 만드는 것입니다. Flutter 화면의 성능이
아니라 최종 제품에 탑재될 네이티브 STT 런타임의 성능을 측정합니다.

## 2. 전체 구성

```text
CI 또는 수동 실행
       │ jobId
       ▼
Flutter Benchmark Orchestrator
├── Job Loader
├── Model Repository
├── Dataset Catalog
├── Benchmark Runner
├── Device Monitor
└── Result Writer/Uploader
       │ Dart FFI
       ▼
Native Engine Bridge
├── whisper.cpp              # 최초 구현 (GGML)
├── sherpa-onnx              # 두 번째 구현 (ONNX Runtime, 공식 Flutter 패키지)
└── TFLite adapter           # 후속 후보
       │
       ▼
Android CPU, GPU 또는 NPU
```

### Flutter가 담당하는 것

- 수동 실행 화면과 진행률 표시
- 런타임 `jobId` 수신 및 Job JSON 조회
- 모델 다운로드, 크기 확인, SHA-256 검증과 캐시 관리
- 내장 데이터셋 manifest 조회와 sample/shard 선택
- asset을 네이티브 엔진이 읽을 수 있는 파일로 준비
- warmup과 측정 반복 순서 제어
- 기기 정보와 메모리/thermal 상태 수집 요청
- 부분 결과, 최종 결과와 실패 결과 저장
- Test Lab artifact 출력 또는 signed URL 업로드

### 네이티브 계층이 담당하는 것

- 모델 context 생성과 해제
- 모델 로딩
- 오디오 전처리와 STT 추론
- 단조 시계 기반의 정밀 시간 측정
- 엔진 버전, backend와 상세 timing 제공
- 플랫폼 프로세스 메모리 수집 지원

큰 PCM 버퍼를 MethodChannel로 반복 복사하지 않습니다. 추론 경로는 FFI를
사용하고, 플랫폼 실행 인자나 OS 전용 정보처럼 호출 빈도가 낮은 기능에만
MethodChannel을 사용합니다.

## 3. 실행 모드

### 수동 모드

`jobId` 없이 앱을 실행하면 사람이 모델, 데이터셋 범위, 스레드 수와 반복 횟수를
선택합니다. 로컬 개발과 단일 실제 기기 검증에 사용합니다.

모델 다운로드는 벤치마크 실행과 분리합니다. `모델 관리` 화면에서 catalog의 모델을
미리 다운로드하고 크기와 SHA-256을 검증합니다. 벤치마크 화면에는 다운로드가
완료된 모델만 노출하며 실행 중에는 네트워크를 사용하지 않습니다.

```text
모델 관리: catalog → 다운로드 → 크기/SHA-256 검증 → 앱 저장소
                                                    ↓
벤치마크:                   다운로드 완료 모델 선택 → 로컬 추론
```

### 자동 모드

테스트 러너가 `jobId`를 전달하면 앱은 화면 입력 없이 다음 과정을 실행합니다.

```text
job 조회 → 모델 준비 → sample 준비 → warmup → 측정 → 결과 저장/업로드 → 종료
```

Android instrumentation argument를 Activity에서 Flutter bootstrap으로 전달하는
작은 네이티브 테스트 러너를 둡니다.

Flutter `integration_test`는 화면 흐름과 기본 통합 동작을 검증하는 smoke test에
사용합니다. 공식 테스트 러너가 보고하는 테스트 전체 시간은 STT 추론 지표로
사용하지 않습니다. 실제 성능 값은 앱과 네이티브 엔진이 직접 측정합니다.

## 4. Benchmark Job

Job은 앱 빌드와 독립적인 런타임 설정입니다. 모델 이름 대신 모델 파일과 실행
조건을 재현할 수 있는 정보를 모두 포함합니다.

```json
{
  "schemaVersion": 1,
  "jobId": "pixel7-base-shard-0",
  "model": {
    "id": "whisper-base-q5_1",
    "version": "1.0.0",
    "engine": "whisper_cpp",
    "url": "https://storage.example.com/models/ggml-base-q5_1.bin",
    "sha256": "MODEL_SHA256",
    "size": 59700000
  },
  "dataset": {
    "id": "sttbench-data",
    "selection": {
      "mode": "shard",
      "shardIndex": 0,
      "shardCount": 8
    }
  },
  "runtime": {
    "language": "ko",
    "threads": 4,
    "backend": "cpu",
    "warmupIterations": 1,
    "measurementIterations": 5,
    "sampleTimeoutSeconds": 1200
  },
  "resultUpload": {
    "url": "SIGNED_UPLOAD_URL"
  }
}
```

지원할 selection mode는 다음 세 가지입니다.

- `all`: manifest에 있는 자동 테스트 대상 전체
- `samples`: 명시한 sample ID만 실행
- `shard`: 전체 대상을 결정적인 규칙으로 분할해 일부 실행

## 5. 실행 상태 머신

```text
idle
  → fetchingJob
  → validatingJob
  → downloadingModel
  → verifyingModel
  → loadingDatasetManifest
  → stagingSample
  → loadingModel
  → warmingUp
  → measuring
  → savingResult
  → uploadingResult
  → completed | failed | cancelled
```

상태가 바뀔 때마다 작은 journal 파일을 원자적으로 갱신합니다. 앱이나 네이티브
엔진이 종료돼도 마지막 성공 단계, 현재 sample과 오류 발생 지점을 확인할 수
있어야 합니다.

현재 Android 수동 실행 구현은 `BenchmarkCoordinator`가 화면과 독립적으로 run을
소유하고, 시작 시 `running` JSON을 만든 뒤 완료/실패/취소 결과와 500ms telemetry를
저장합니다. persistent Flutter engine, foreground service와 partial wake lock을
사용합니다. 세부 동작과 플랫폼 제한은
`BACKGROUND_MONITORING_AND_TRANSFER.md`에 정리합니다.

한 Job에서는 원칙적으로 하나의 모델만 실행합니다. 여러 모델을 같은 프로세스에서
연속 실행하면 allocator 상태, 캐시와 thermal 상태가 다음 모델에 영향을 줄 수 있기
때문입니다.

## 6. 엔진 추상화

실제 구현은 `benchmark_services.dart`의 다음 인터페이스를 두 엔진이 각각
구현하는 형태입니다. 초기 설계 스케치보다 훨씬 얇습니다 — `AudioSample`/
`DownloadedModel`/`BenchmarkResult`를 그대로 주고받아서, `BenchmarkCoordinator`
와 그 이후(텔레메트리, 결과 저장/전송, 결과 화면)는 어떤 엔진이 실행됐는지
전혀 몰라도 됩니다.

```dart
abstract interface class SttBenchmarkEngine {
  Future<BenchmarkResult> run({
    required AudioSample sample,
    required DownloadedModel model,
    required int threads,
    required void Function(int value) onProgress,
    void Function()? onInferenceStarted,
  });
}
```

- `WhisperBenchmarkEngine` (`benchmark_services.dart`): `whisper_ggml` 플러그인을
  통해 whisper.cpp를 호출합니다. FFI는 플러그인 내부에 캡슐화되어 있습니다.
- `SherpaOnnxEngine` (`sherpa_engine.dart`): 공식 `sherpa_onnx` Flutter 패키지를
  사용합니다. 벤더링된 C API 대신 pub.dev 패키지가 Android/iOS별 prebuilt
  라이브러리를 그대로 제공하므로, whisper.cpp처럼 별도 네이티브 바인딩 코드를
  직접 작성하지 않습니다. `ModelSpec.engine`에 따라
  `sherpa_onnx.OnlineRecognizer`(스트리밍 Zipformer, 100ms 청크 입력)나
  `sherpa_onnx.OfflineRecognizer`(SenseVoice, 파일 전체 한 번에 입력) 중 하나로
  분기합니다.
- `BenchmarkCoordinator._engineFor(ModelSpec)`가 `ModelSpec.engine` 값을 보고
  둘 중 실행할 엔진을 고릅니다.

sherpa-onnx 모델은 `.tar.bz2`로 배포되므로 `ModelRepository`가 다운로드+SHA-256
검증까지는 whisper.cpp 모델과 동일하게 처리하고, 그 뒤 `archive` 패키지
(순수 Dart BZip2/Tar 디코더)로 앱 저장소 안에서 한 번만 압축을 풉니다.

## 7. 플랫폼 테스트 자동화

### Android

- Benchmark App APK는 실제 배포와 가까운 release/profileable 구성으로 빌드합니다.
- 별도 Test APK가 instrumentation argument의 `jobId`를 읽습니다.
- Test APK는 앱을 실행하고 완료 신호 또는 실패/timeout을 기다립니다.
- 결과 JSON과 journal을 Test Lab이 수집할 디렉터리에 저장합니다.

Test Lab이 표시하는 테스트 소요 시간이 아니라 결과 JSON 안의
네이티브 측정값을 성능 수치로 사용합니다.

## 8. 보안과 재현성

- 모든 모델 다운로드는 HTTPS를 사용합니다.
- 모델 크기와 SHA-256을 로딩 전에 검증합니다.
- 앱에 장기 Storage credential이나 service account key를 넣지 않습니다.
- 결과 업로드는 짧은 수명의 signed URL을 사용합니다.
- 결과에는 앱 버전, Git revision, 모델 hash, 데이터 manifest hash와 엔진 버전을
  기록합니다.
- 모델을 로드하기 전에 가용 저장공간과 예상 최소 RAM 조건을 확인합니다.
- 다운로드 중단은 임시 파일로 처리하고 검증이 끝난 뒤 최종 파일명으로 바꿉니다.
