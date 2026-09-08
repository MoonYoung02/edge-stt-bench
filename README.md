# EdgeSTT Bench

EdgeSTT Bench는 Whisper 한 종류에 묶이지 않고 여러 로컬 STT 엔진을 데스크톱과
Android 실제 기기에서 같은 방식으로 실행하며, 원본 출력과 비교 가능한 공통
출력을 모두 보존하는 벤치마크 프로젝트입니다.

Android 실제 기기용 Flutter 벤치마크 앱은
[`mobile_bench/`](mobile_bench/README.md)에서 확인할 수 있습니다.

모바일 앱은 단일 오디오 수동 실행과 정답이 있는 KCSC 22개 샘플의 자동 순차
실행을 지원합니다. 모바일에서 내보낸 결과는 동일한 Python CER/WER 구현으로
채점하거나 이 프로젝트의 `runs/` 구조로 변환할 수 있습니다. 실행 및 결과 수집
방법은 모바일 앱 README의
[모바일 결과 채점과 변환](mobile_bench/README.md#모바일-결과-채점과-변환)을
참고하세요.

## 가장 자주 쓰는 명령

가상환경을 켠 뒤 환경과 모델 상태를 확인합니다.

```bash
source .venv/bin/activate
python cli.py doctor
python cli.py models
```

오디오 하나를 자세히 확인합니다. WAV뿐 아니라 M4A, MP3, FLAC, OGG, OPUS,
AAC, MP4, WebM 등을 받을 수 있습니다.

```bash
python cli.py inspect "테스트 녹음본.m4a" --model whisper-cpp-base-q5_1
python cli.py inspect data/kcsc/WAV/A0051_S0001_0_G0101.wav --model large-v3-turbo
```

실행 장치를 직접 고르려면 `--device cpu` 또는 `--device mps`를 사용합니다.

```bash
python cli.py inspect data/kcsc/WAV/A0051_S0001_0_G0101.wav \
  --model large-v3-turbo \
  --device mps \
  --language ko
```

모노 음성의 화자를 분리하려면 `--diarize`를 사용합니다. 화자 수를 알고 있으면
`--speakers`로 지정하는 편이 안정적이며, 이 옵션만 붙여도 화자 분리가 자동으로
켜집니다.

```bash
python cli.py inspect "테스트 녹음본.m4a" \
  --model large-v3-turbo \
  --language ko \
  --diarize \
  --speakers 2
```

화자 분리는 별도 `.venv-diarization`의
`pyannote/speaker-diarization-community-1`을 사용합니다. 최초 준비에는 Hugging
Face 모델 사용 조건 동의와 `hf auth login`이 필요합니다.

기본 언어는 자동 감지입니다. 한국어로 고정하려면 `--language ko`를 붙입니다.
실행 중 진행률과 ETA가 표시되고, 종료 후 실제 실행 시간과 RTF가 표시됩니다.

## KCSC 전체 ASR 평가

KCSC는 학술 연구 목적으로만 사용할 수 있고 상업적 사용은 허용되지 않습니다.
학생 프로젝트에서 출처를 표기하고 사용한다는 전제에서 다음 명령으로 내려받습니다.
원본과 가공 파일의 무단 재배포도 허용되지 않으므로 `data/`는 Git에 포함하지
않습니다.

```bash
python cli.py download
```

파일은 Git에서 제외된 `data/kcsc/WAV`와 `data/kcsc/TXT`에 저장됩니다. 준비가
끝나면 다음 명령을 실행합니다. 모델은 전체 평가에서 한 번만 로드됩니다.

```bash
python cli.py evaluate \
  --dataset kcsc \
  --model large-v3-turbo \
  --device mps \
  --language ko
```

CPU로 비교하거나 앞에서 일부만 빠르게 확인할 수도 있습니다.

```bash
python cli.py evaluate --dataset kcsc --model base --device cpu --limit 3
```

중단되었거나 일부 샘플이 실패한 같은 설정의 최신 실행을 이어가려면
`--resume`을 붙입니다.

```bash
python cli.py evaluate --dataset kcsc --model large-v3-turbo --device mps --resume
```

전체 평가는 `runs/<실행ID>/summary.json`과 `summary.md`를 만들고, 각 샘플에는
다음 핵심 파일을 저장합니다.

- `prediction.json`: 모델·장치·구간·전사·실행 시간
- `prediction.md`: KCSC 정답 TXT와 같은 행 형식의 사람이 읽는 예측 전사
- `reference.txt`: 평가에 사용한 원본 정답의 사본
- `comparison.json`: 정규화된 정답/예측 및 CER/WER
- `segments.csv`, `words.csv`, `tokens.csv`: 상세 예측 단위
- `raw/result.json`, `raw/engine.log`: 엔진 원본 출력과 로그

전체 CER/WER의 `micro`는 모든 오류 수와 정답 단위 수를 합산한 값이고,
`macro`는 샘플별 오류율의 평균입니다. 한국어 WER는 공백으로 나눈 어절에
민감하므로 CER을 주 지표, WER을 보조 지표로 보는 것을 권장합니다.

### 모든 모델을 CPU와 MPS에서 평가

등록된 모델마다 CPU 평가를 먼저 실행하고 이어서 MPS 평가를 실행합니다. 없는
Python Whisper 체크포인트는 최초 실행 시 공식 캐시에 자동 다운로드하고,
whisper.cpp 모델은 `models/`에 자동으로 준비합니다. 한 조합이 실패해도 다음
조합은 계속 실행됩니다.

먼저 모델·장치별 KCSC 한 파일로 전체 조합을 점검하는 것을 권장합니다.
`evaluate-all`은 기본적으로 모든 모델을 CPU에서만 실행합니다.

```bash
python cli.py evaluate-all --dataset kcsc --limit 1
```

점검이 끝나면 `--limit` 없이 전체 데이터를 평가합니다.

```bash
python cli.py evaluate-all --dataset kcsc
```

특정 모델 또는 장치만 선택할 수도 있습니다.

```bash
python cli.py evaluate-all \
  --dataset kcsc \
  --models base small large-v3-turbo \
  --devices cpu mps \
  --limit 3
```

각 모델·장치 결과는 기존 `runs/` 실행 폴더에 독립적으로 저장되고, 전체 비교는
별도의 `runs/<실행ID>__kcsc-matrix/summary.json`과 `summary.md`에 저장됩니다.
전체 모델의 CPU 평가는 매우 오래 걸릴 수 있으며, 매 조합 사이에는 모델 메모리를
정리합니다.

패키지 형태의 명령도 동일하게 사용할 수 있습니다.

```bash
python -m sttbench doctor
python -m sttbench inspect "테스트 녹음본.m4a" --model base
```

### whisper.cpp 크기·양자화 비교

whisper.cpp GGML 양자화 모델(tiny/base/small/medium × Q5/Q8, 총 8개, `config/models.yaml`의
`whisper-cpp-*` 항목)을 CPU에서 한 번에 비교하려면 전용 스크립트를 사용합니다.
내부적으로 위 `evaluate-all --devices cpu`를 그대로 호출하므로 결과 위치와 형식은
동일합니다.

```bash
# 먼저 샘플 1개로 8개 모델이 다 정상 동작하는지 점검
./scripts/whisper_cpp_matrix.sh smoke

# 문제없으면 KCSC 전체로 실제 비교 실행 (모델이 클수록 오래 걸림)
./scripts/whisper_cpp_matrix.sh full
```

결과는 `runs/<실행ID>__kcsc-matrix/summary.md`에 모델별 CER/WER/RTF 비교표로
저장됩니다. large-v3-turbo/large-v3는 샘플 1개에도 CPU에서 8분 안팎 걸려 기본
대상에서 뺐습니다. 필요하면 `config/models.yaml`에 해당 모델을 다시 등록하고
`scripts/whisper_cpp_matrix.sh`의 `MODELS` 배열에 추가하세요.

## 모델 추가

모델 선택지는 [config/models.yaml](config/models.yaml) 한 곳에서 관리합니다.

```yaml
models:
  my-model:
    adapter: whisper_python
    checkpoint: base
    device: mps
```

새 엔진은 `sttbench/adapters/base.py`의 `STTAdapter` 계약을 구현하고
`sttbench/registry.py`에 한 번 연결합니다. 이후 실행·시간 측정·결과 저장·정답
비교 코드는 그대로 재사용합니다.

현재 어댑터는 다음 두 개입니다.

- `whisper_python`: `openai-whisper`, Apple MPS
- `whisper_cpp`: `whisper.cpp`, CPU. tiny/base/small/medium(Q5·Q8) 총 8개 GGML
  양자화 모델이 `whisper-cpp-*` 이름으로 등록되어 있습니다. 크기·양자화 전체를
  한 번에 비교하는 방법은 위 [whisper.cpp 크기·양자화 비교](#whispercpp-크기양자화-비교)를
  참고하세요.

## 결과 폴더

새 실행은 서로 덮어쓰지 않도록 `runs/` 아래에 생성됩니다.

```text
runs/<실행ID>/
├── run.json                 # 실행 환경과 전체 설정
├── summary.json             # 시간, RTF, 개수, CER/WER 요약
└── samples/<오디오>/
    ├── raw/                 # 모델 고유 원본 JSON/로그/자막
    ├── transcript.json      # 엔진 공통 형식
    ├── transcript.txt
    ├── transcript.srt
    ├── transcript.vtt
    ├── transcript_labeled.txt
    ├── diarization.json       # 겹침 포함 화자 구간
    ├── exclusive_diarization.json
    ├── diarization.rttm
    ├── overlap_segments.json
    ├── speaker_transcript.json
    ├── speaker_transcript.txt
    ├── segments.csv
    ├── words.csv
    ├── tokens.csv
    ├── audio_16k_mono.npy
    ├── log_mel_spectrogram.npy
    ├── waveform.png
    └── audio_spectrogram.png
```

같은 이름의 KCSC 정답 TXT가 있으면 다음 파일도 생성합니다.

- `reference_labeled.txt`: `[시작,종료] 화자 성별 정답문` 원본
- `reference.json`: 구조화한 정답
- `comparison.json`: 전체 CER/WER

`transcript_labeled.txt`에는 모델이 실제로 화자를 예측한 경우에만 화자 ID를
씁니다. 현재 Whisper 모델들은 화자 분리를 하지 않으므로 `unknown`입니다.
정답의 화자 ID를 예측값처럼 복사하지 않아 향후 화자 분리 성능을 올바르게
평가할 수 있습니다.

## 프로젝트 구조

```text
sttbench/
├── cli.py, runner.py        # 사용자 명령과 단일 파일 실행 흐름
├── evaluator.py             # KCSC 전체 평가와 결과 집계
├── matrix.py                # 모든 모델·장치 조합 순차 평가
├── schema.py                # 공통 Transcript 형식
├── registry.py              # YAML 모델 레지스트리
├── artifacts.py, progress.py
├── adapters/                # STT 엔진별 차이
├── datasets/                # KCSC와 JSONL manifest
├── diarization*.py          # inspect 전용 pyannote 화자 분리(세그먼트·RTTM)
└── metrics/                 # CER/WER; KCSC 정답 대비 화자 분리 정확도는 다음 단계
```

KCSC 다운로드 명령은 다음과 같습니다.

```bash
python cli.py download
```

## 자체 테스트

```bash
python -m unittest discover -s tests -v
```
