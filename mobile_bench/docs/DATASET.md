# 내장 데이터셋 설계

## 1. 결정 사항

저장소 루트의 `data/` 전체를 Flutter 앱 빌드에 포함합니다. 모델만 실행 시 원격
다운로드합니다.

이 방식의 목적은 다음과 같습니다.

- 모든 기기에 정확히 같은 오디오와 정답 제공
- 네트워크 속도와 실패가 데이터셋 준비에 미치는 영향 제거
- Test Lab 실행 단위의 독립성 보장
- 모델만 교체하는 반복 실험 단순화

대신 `data/`가 바뀌면 앱을 다시 빌드해야 하므로 앱 버전과 데이터셋 버전을 함께
관리합니다.

## 2. 현재 데이터 스냅샷

2026-09-06 기준 현재 저장소의 `data/`는 다음과 같습니다.

| 항목 | 값 |
|---|---:|
| 전체 크기 | 약 595MB |
| 전체 파일 | 45개 |
| KCSC WAV | 22개 |
| KCSC 정답 TXT | 22개 |
| 기타 M4A | 1개 |
| 전체 음성 파일 | 23개 |
| 전체 음성 길이 | 19,637.852초, 약 5.455시간 |

`data/테스트 녹음본.m4a`에는 대응하는 정답 TXT가 없으므로 기본 정확도 테스트
대상에서는 제외하고 수동/inspection 그룹으로 분류합니다.

## 3. 빌드 패키징

원본은 저장소 루트 `data/` 한 곳에서만 관리합니다. 현재 MVP는 상대 symlink를
통해 원본을 Flutter asset으로 노출합니다.

```text
../data/
  ← mobile_bench/assets/data
  → Flutter 앱 빌드
```

따라서 데이터가 두 번 저장되지는 않지만 APK에는 실제 파일 전체가 포함됩니다.
현재 빌드에서는 APK 안에 음성 23개와 TXT 22개가 포함된 것을 확인했습니다.

향후 Firebase Test Lab 자동화를 붙일 때 manifest 생성과 전체 파일 hash 검증을
추가합니다. 현재 MVP는 Flutter의 `AssetManifest`에서 파일 목록을 읽고 WAV/TXT를
파일명으로 연결합니다.

## 4. Dataset Manifest 목표

Flutter 런타임에서 asset 디렉터리를 탐색하지 않고 명시적인 manifest를 사용합니다.

```json
{
  "schemaVersion": 1,
  "datasetId": "sttbench-data",
  "datasetVersion": "2026-09-06",
  "manifestSha256": "MANIFEST_SHA256",
  "samples": [
    {
      "id": "A0051_S0001_0_G0101",
      "audioAsset": "assets/data/kcsc/WAV/A0051_S0001_0_G0101.wav",
      "referenceAsset": "assets/data/kcsc/TXT/A0051_S0001_0_G0101.txt",
      "format": "wav",
      "durationSeconds": 875.2,
      "audioSha256": "AUDIO_SHA256",
      "referenceSha256": "REFERENCE_SHA256",
      "group": "kcsc",
      "defaultEnabled": true
    },
    {
      "id": "manual-recording",
      "audioAsset": "assets/data/테스트 녹음본.m4a",
      "referenceAsset": null,
      "format": "m4a",
      "durationSeconds": 301.1,
      "audioSha256": "AUDIO_SHA256",
      "group": "manual",
      "defaultEnabled": false
    }
  ]
}
```

파일 경로에 한글이 있어도 manifest의 ID로 접근하고 UI나 Job에서 원본 경로를 직접
조합하지 않습니다.

## 5. Asset staging

Flutter asset은 네이티브 엔진이 일반 파일 경로로 바로 읽을 수 있다고 가정하지
않습니다. 실행할 오디오 한 개만 앱 cache로 준비한 뒤 그 경로를 FFI에 전달합니다.

```text
asset에서 선택 sample 확인
  → cache에 streaming copy
  → 복사된 파일 SHA-256 검증
  → staging buffer 정리
  → 메모리 baseline 측정
  → 추론
  → 임시 파일 삭제 또는 다음 반복에서 재사용
```

전체 595MB를 한 번에 추출하지 않습니다. 전체를 복제하면 설치 파일과 추출본이
동시에 존재해 저장공간 요구량이 크게 늘어납니다.

`assetStagingSeconds`는 기록하되 모델 성능 시간과 RTF에서 제외합니다.

## 6. Shard 규칙

전체 원본 음성이 약 5.455시간이므로 모든 모델을 하나의 테스트 실행에서 처리하지
않습니다. APK에는 전체 데이터를 넣되 Job은 일부 sample만 선택합니다.

Shard는 파일 개수가 아니라 `durationSeconds` 합계가 최대한 비슷하도록 결정적으로
분할합니다. 동일한 `manifestSha256`, `shardCount`와 알고리즘 버전에서는 항상 같은
sample 집합이 나와야 합니다.

```json
{
  "selection": {
    "mode": "shard",
    "shardIndex": 0,
    "shardCount": 8,
    "algorithm": "balanced-duration-v1"
  }
}
```

결과에는 shard 정보뿐 아니라 실제 실행한 모든 sample ID를 기록합니다. 여러 shard
결과를 합칠 때 누락과 중복을 검증합니다.

## 7. 오디오 형식

- KCSC WAV는 기본 자동 벤치마크 및 정확도 평가에 사용합니다.
- WAV, M4A, MP3, FLAC, OGG, OPUS, AAC, MP4, WebM, CAF, AIFF, 3GP와 AMR을
  오디오 asset으로 인식합니다.
- 모든 입력은 Android에 포함된 FFmpeg에서 16 kHz, mono, signed 16-bit PCM
  WAV로 정규화한 뒤 whisper.cpp에 전달합니다. 따라서 컨테이너나 sample rate가
  달라도 같은 추론 입력 조건을 유지합니다.
- asset의 한글, 공백과 중복 파일명은 앱 cache에서 SHA-256 기반 ASCII 파일명으로
  바꿔 native 라이브러리에 전달합니다. 화면과 결과에는 원래 파일명을 유지합니다.
- 전처리 비용을 비교하려면 원본 파일 decoding을 포함한 시간과 PCM 준비 후 순수
  추론 시간을 분리합니다.
- CER/WER 계산에는 대응하는 `referenceAsset`이 있는 sample만 사용합니다.
