#!/usr/bin/env bash
# 사용법: pull_benchmark_results.sh [--recent N] [SERIAL] [OUTPUT_DIR]
#
#   --recent N   기기에 있는 결과 중 최근 수정된 N개만 가져옵니다(기본: 전체).
#   SERIAL       adb 기기 시리얼(생략하면 연결된 첫 기기).
#   OUTPUT_DIR   저장 위치(기본: ./benchmark-results).
set -euo pipefail

if [[ -n "${ADB_BIN:-}" ]]; then
  adb_bin="$ADB_BIN"
elif command -v adb >/dev/null 2>&1; then
  adb_bin="$(command -v adb)"
elif [[ -x /opt/homebrew/share/android-commandlinetools/platform-tools/adb ]]; then
  adb_bin="/opt/homebrew/share/android-commandlinetools/platform-tools/adb"
else
  echo "adb를 찾지 못했습니다. Android platform-tools를 PATH에 추가하거나 ADB_BIN을 지정하세요." >&2
  exit 1
fi

recent_limit=""
positional=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recent)
      recent_limit="${2:-}"
      if [[ -z "$recent_limit" || ! "$recent_limit" =~ ^[0-9]+$ || "$recent_limit" -lt 1 ]]; then
        echo "--recent 뒤에는 1 이상의 정수를 지정하세요." >&2
        exit 1
      fi
      shift 2
      ;;
    --recent=*)
      recent_limit="${1#--recent=}"
      if [[ ! "$recent_limit" =~ ^[0-9]+$ || "$recent_limit" -lt 1 ]]; then
        echo "--recent 뒤에는 1 이상의 정수를 지정하세요." >&2
        exit 1
      fi
      shift
      ;;
    *)
      positional+=("$1")
      shift
      ;;
  esac
done

serial="${positional[0]:-}"
output_root="${positional[1]:-./benchmark-results}"

if [[ -z "$serial" ]]; then
  serial="$($adb_bin devices | awk 'NR > 1 && $2 == "device" { print $1; exit }')"
fi

if [[ -z "$serial" ]]; then
  echo "연결된 Android 기기를 찾지 못했습니다." >&2
  exit 1
fi

target="$output_root/$serial"
mkdir -p "$target"

package="com.moonyoung.sttbench.mobile_bench"

# 기기 쪽 파일 목록을 최근 수정 순으로 받아 앞에서 N개만 고릅니다.
# ls -t는 최신 항목이 먼저 나오므로 head -n으로 그대로 잘라내면 됩니다.
select_recent() {
  local all_files="$1"
  if [[ -z "$recent_limit" ]]; then
    printf '%s' "$all_files"
  else
    printf '%s' "$all_files" | head -n "$recent_limit"
  fi
}

# Debuggable builds can stream private result JSON directly over adb, so the
# user does not need to press Export for every run.
if "$adb_bin" -s "$serial" shell run-as "$package" test -d files/results 2>/dev/null; then
  if [[ -z "$recent_limit" ]]; then
    echo "[$serial] 앱 내부 STTBench 결과 수집 → $target"
    "$adb_bin" -s "$serial" exec-out run-as "$package" \
      tar -cf - -C files/results . | tar -xf - -C "$target"
    exit 0
  fi

  echo "[$serial] 앱 내부 STTBench 결과 중 최근 ${recent_limit}개 수집 → $target"
  all_files="$("$adb_bin" -s "$serial" shell run-as "$package" sh -c 'ls -t files/results 2>/dev/null' | tr -d '\r')"
  selected="$(select_recent "$all_files")"
  if [[ -z "$selected" ]]; then
    echo "가져올 결과 파일이 없습니다." >&2
    exit 1
  fi
  # shellcheck disable=SC2086
  "$adb_bin" -s "$serial" exec-out run-as "$package" \
    tar -cf - -C files/results $selected | tar -xf - -C "$target"
  echo "수집 완료: $target ($(printf '%s\n' "$selected" | wc -l | tr -d ' ')개)"
  exit 0
fi

# Release builds normally disallow run-as. In that case, press Export on the
# result page first and pull the public Downloads directory.
remote_results="/sdcard/Download/STTBench/results"
if ! "$adb_bin" -s "$serial" shell test -d "$remote_results"; then
  echo "휴대폰에서 $remote_results 폴더를 찾지 못했습니다." >&2
  echo "앱 결과 화면에서 '파일 내보내기'를 먼저 누르세요." >&2
  exit 1
fi

if [[ -z "$recent_limit" ]]; then
  echo "[$serial] Downloads의 STTBench 결과 수집 → $target"
  # '/.'을 붙여 results 디렉터리 자체가 아니라 그 안의 파일을 target에 복사합니다.
  "$adb_bin" -s "$serial" pull "$remote_results/." "$target"
  echo "수집 완료: $target"
  exit 0
fi

echo "[$serial] Downloads의 STTBench 결과 중 최근 ${recent_limit}개 수집 → $target"
all_files="$("$adb_bin" -s "$serial" shell "ls -t $remote_results" | tr -d '\r')"
selected="$(select_recent "$all_files")"
if [[ -z "$selected" ]]; then
  echo "가져올 결과 파일이 없습니다." >&2
  exit 1
fi
count=0
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  "$adb_bin" -s "$serial" pull "$remote_results/$name" "$target/" >/dev/null
  count=$((count + 1))
done <<< "$selected"
echo "수집 완료: $target (${count}개)"
