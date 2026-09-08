#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
serial="${1:-}"
output_root="${2:-./benchmark-results}"

echo "5초마다 새 벤치마크 결과를 확인합니다. 중지는 Ctrl+C입니다."
while true; do
  "$script_dir/pull_benchmark_results.sh" "$serial" "$output_root" || true
  sleep 5
done
