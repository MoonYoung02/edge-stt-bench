# 모바일 STT 벤치마크 규약

## 1. 목적

모델, 엔진, 기기와 실행 옵션이 달라도 비교 가능한 결과를 만들기 위한 공통 측정
규약입니다. 성능 숫자만 저장하지 않고 결과를 재현하는 데 필요한 입력과 환경을
같이 저장합니다.

## 2. 측정 경계

```text
앱 시작
  → Job 조회                  측정하지만 STT 성능에서 제외
  → 모델 다운로드/검증        측정하지만 STT 성능에서 제외
  → asset staging             측정하지만 STT 성능에서 제외
  → 모델 로드                 modelLoadSeconds
  → warmup                    warmupSeconds, 통계에서 제외
  → 오디오 전처리             preprocessSeconds
  → STT 추론                  inferenceSeconds
  → transcript 후처리         postprocessSeconds
  → 결과 저장/업로드          측정하지만 STT 성능에서 제외
```

주요 계산식은 다음과 같습니다.

```text
RTF = inferenceSeconds / audioSeconds
endToEndRTF = (preprocessSeconds + inferenceSeconds + postprocessSeconds)
              / audioSeconds
```

`RTF < 1`이면 해당 조건에서 오디오 길이보다 빠르게 추론했다는 뜻입니다.

## 3. 반복 조건

- 모델 로딩과 cold inference는 별도 시나리오로 측정합니다.
- 성능 통계 전에 최소 1회 warmup을 수행합니다.
- 기본 측정은 sample당 5회로 합니다.
- 평균만 사용하지 않고 median, p90, min과 max를 기록합니다.
- 모든 반복에서 transcript hash도 기록해 비결정적인 결과를 확인합니다.
- 각 반복 시작 전 thermal 상태를 확인하고 심각한 throttling 상태면 대기하거나
  해당 반복을 invalid로 표시합니다.
- timeout, OOM과 native crash도 성능 결과의 일부로 보존합니다.

정확도 전체 데이터 실행에서는 비용을 줄이기 위해 sample당 1회만 실행할 수
있습니다. 이 경우 Job의 목적을 `accuracy`로 명시해 반복 성능 Job과 구분합니다.

## 4. 필수 지표

| 분류 | 지표 |
|---|---|
| 입력 | 오디오 길이, format, sample ID와 hash |
| 준비 | asset staging, 모델 다운로드와 검증 시간 |
| 로딩 | 모델 로딩 시간과 로딩 전후 메모리 |
| 추론 | 전처리, inference, 후처리와 end-to-end 시간 |
| 처리량 | RTF, end-to-end RTF |
| 메모리 | baseline, 모델 로딩 후, peak, dispose 후 메모리 |
| 시스템 | thermal 상태, OS, 아키텍처, 전체 RAM |
| 품질 | transcript, transcript hash, 언어 |
| 안정성 | timeout, OOM, crash, invalid iteration |

CPU와 프로세스 메모리는 500ms 간격 telemetry로 구현합니다. CPU는 프로세스 누적
CPU 시간의 차이를 사용하고, 메모리는 Android PSS를 사용합니다. 발열은 Android
thermal status/headroom을 기록합니다.
GPU/NPU 사용량과 에너지는 플랫폼에서 신뢰할 수 있는 공통 수집 방법이 확보된 뒤
선택 지표로 추가합니다.

## 5. 메모리 측정

Dart heap만 측정하면 C/C++ 모델 메모리가 누락되므로 앱 프로세스 전체를
측정합니다. 측정 방법은 플랫폼별로 다를 수 있어 결과에 method를 명시합니다.

```json
{
  "memory": {
    "measurementMethod": "android-process-pss",
    "sampleIntervalMs": 100,
    "baselineMb": 84.2,
    "afterModelLoadMb": 312.7,
    "peakMb": 498.3,
    "afterDisposeMb": 102.1,
    "modelLoadDeltaMb": 228.5
  }
}
```

모니터링은 모델 로딩 직전부터 모델 dispose 후까지 이어집니다. asset staging용
임시 메모리가 baseline을 오염시키지 않도록 staging이 끝난 뒤 측정을 시작합니다.

## 6. 결과 스키마 초안

```json
{
  "schemaVersion": 1,
  "runId": "20260906-pixel7-base-s0",
  "jobId": "pixel7-base-shard-0",
  "status": "completed",
  "app": {
    "version": "0.1.0",
    "buildNumber": "1",
    "gitRevision": "REVISION"
  },
  "device": {
    "platform": "android",
    "manufacturer": "Google",
    "model": "Pixel 7",
    "osVersion": "16",
    "architecture": "arm64-v8a",
    "totalMemoryMb": 7980
  },
  "model": {
    "id": "whisper-base-q5_1",
    "version": "1.0.0",
    "sha256": "MODEL_SHA256",
    "size": 59700000
  },
  "dataset": {
    "id": "sttbench-data",
    "version": "2026-09-06",
    "manifestSha256": "MANIFEST_SHA256",
    "selection": {
      "mode": "shard",
      "shardIndex": 0,
      "shardCount": 8,
      "algorithm": "balanced-duration-v1"
    }
  },
  "runtime": {
    "engine": "whisper.cpp",
    "engineVersion": "ENGINE_VERSION",
    "backend": "cpu",
    "threads": 4,
    "language": "ko"
  },
  "samples": [
    {
      "sampleId": "A0051_S0001_0_G0101",
      "audioSha256": "AUDIO_SHA256",
      "audioSeconds": 875.2,
      "assetStagingSeconds": 0.18,
      "modelLoadSeconds": 0.82,
      "iterations": [
        {
          "index": 0,
          "valid": true,
          "preprocessSeconds": 0.12,
          "inferenceSeconds": 42.5,
          "postprocessSeconds": 0.03,
          "rtf": 0.0486,
          "peakMemoryMb": 498.3,
          "thermalBefore": "nominal",
          "thermalAfter": "fair",
          "transcript": "...",
          "transcriptSha256": "TRANSCRIPT_SHA256"
        }
      ]
    }
  ],
  "summary": {
    "sampleCount": 1,
    "audioSeconds": 875.2,
    "medianRtf": 0.0486,
    "p90Rtf": 0.0486,
    "peakMemoryMb": 498.3
  },
  "warnings": []
}
```

## 7. 실패 결과

실패해도 가능한 범위의 환경과 측정값을 보존합니다.

```json
{
  "schemaVersion": 1,
  "runId": "20260906-lowend-base-s0",
  "jobId": "lowend-base-shard-0",
  "status": "failed",
  "failure": {
    "stage": "loadingModel",
    "code": "OUT_OF_MEMORY",
    "message": "Native model initialization failed",
    "lastSampleId": null
  }
}
```

인증 token, signed URL과 로컬의 민감한 절대 경로는 결과나 로그에 기록하지 않습니다.

## 8. 기존 sttbench 연동

모바일 앱은 원본 transcript와 timing을 손실 없이 저장합니다. Python 쪽 importer는
다음 작업을 담당합니다.

1. 결과 schema와 hash 검증
2. 여러 device/shard 결과 병합
3. sample 누락 및 중복 검사
4. 기존 텍스트 정규화 규칙 적용
5. CER/WER 계산
6. 모델 × 기기 × backend × 스레드 비교표 생성

이렇게 하면 데스크톱 실행과 모바일 실행이 동일한 정확도 계산 구현을 공유합니다.
