#!/usr/bin/env bash
# whisper.cpp 크기 x 양자화(Q5/Q8) 조합을 CPU에서 순차 평가합니다.
#
# 사용법:
#   scripts/whisper_cpp_matrix.sh smoke   # 기본값. 8개 모델 x CPU, 샘플 1개로 빠르게 점검
#   scripts/whisper_cpp_matrix.sh full    # KCSC 전체 데이터로 8개 모델 x CPU 평가
#
# 대상 모델 (mobile_bench가 검증한 공식 GGML 양자화 카탈로그 중 tiny~medium):
#   tiny/base/small: Q5_1, Q8_0
#   medium: Q5_0, Q8_0
#
# large-v3-turbo/large-v3는 샘플 1개에도 CPU에서 8분 안팎이 걸려 시간 대비
# 효율이 낮아 기본 대상에서 뺐습니다. 필요하면 config/models.yaml에
# whisper-cpp-large-v3-turbo-q5_0 등을 다시 추가하고 아래 MODELS 배열에 넣으세요.
# MPS/Metal은 의도적으로 제외했습니다. CPU 결과만 비교합니다.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

MODELS=(
  whisper-cpp-tiny-q5_1
  whisper-cpp-tiny-q8_0
  whisper-cpp-base-q5_1
  whisper-cpp-base-q8_0
  whisper-cpp-small-q5_1
  whisper-cpp-small-q8_0
  whisper-cpp-medium-q5_0
  whisper-cpp-medium-q8_0
)

MODE="${1:-smoke}"

case "$MODE" in
  smoke|full) ;;
  *)
    echo "사용법: $0 [smoke|full]" >&2
    echo "  smoke (기본): --limit 1로 11개 모델 x CPU 조합만 빠르게 점검" >&2
    echo "  full        : KCSC 전체 데이터로 11개 모델 x CPU 평가 (오래 걸릴 수 있음)" >&2
    exit 1
    ;;
esac

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "== 환경 점검 =="
python cli.py doctor

LIMIT_ARGS=()
if [[ "$MODE" == "smoke" ]]; then
  LIMIT_ARGS=(--limit 1)
  echo
  echo "== 스모크 테스트: whisper.cpp 8개 모델 x CPU, 샘플 1개 =="
  echo "(모델 파일이 없으면 이 단계에서 자동 다운로드됩니다)"
else
  echo
  echo "== 전체 평가: whisper.cpp 8개 모델 x CPU, KCSC 전체 =="
  echo "모델이 클수록 CPU 실행 시간이 길어질 수 있습니다. smoke로 먼저 점검하는 것을 권장합니다."
fi

python cli.py evaluate-all \
  --dataset kcsc \
  --models "${MODELS[@]}" \
  --devices cpu \
  "${LIMIT_ARGS[@]}"

echo
echo "완료. 비교 결과는 runs/<실행ID>__kcsc-matrix/summary.md 에서 확인하세요."
echo "모델 ID 자체에 크기와 양자화가 포함되어 있어(예: whisper-cpp-medium-q8_0)"
echo "summary.md 표만으로 크기 x 양자화 x CER/WER/RTF 비교가 바로 됩니다."
