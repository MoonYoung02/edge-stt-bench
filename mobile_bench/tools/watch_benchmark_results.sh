#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"

echo "5초마다 새 벤치마크 결과를 확인합니다. 중지는 Ctrl+C입니다."
echo "(pull_benchmark_results.sh와 동일한 인자를 받습니다: [--recent N] [SERIAL] [OUTPUT_DIR])"
while true; do
  "$script_dir/pull_benchmark_results.sh" "$@" || true
  sleep 5
done
