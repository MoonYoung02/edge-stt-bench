#!/usr/bin/env bash
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
serial="${1:-}"
output_root="${2:-./benchmark-results}"

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

# Debuggable builds can stream private result JSON directly over adb, so the
# user does not need to press Export for every run.
if "$adb_bin" -s "$serial" shell run-as "$package" test -d files/results 2>/dev/null; then
  echo "[$serial] 앱 내부 STTBench 결과 수집 → $target"
  "$adb_bin" -s "$serial" exec-out run-as "$package" \
    tar -cf - -C files/results . | tar -xf - -C "$target"
  exit 0
fi

# Release builds normally disallow run-as. In that case, press Export on the
# result page first and pull the public Downloads directory.
echo "[$serial] Downloads의 STTBench 결과 수집 → $target"
remote_results="/sdcard/Download/STTBench/results"
if ! "$adb_bin" -s "$serial" shell test -d "$remote_results"; then
  echo "휴대폰에서 $remote_results 폴더를 찾지 못했습니다." >&2
  echo "앱 결과 화면에서 '파일 내보내기'를 먼저 누르세요." >&2
  exit 1
fi

# '/.'을 붙여 results 디렉터리 자체가 아니라 그 안의 파일을 target에 복사합니다.
"$adb_bin" -s "$serial" pull "$remote_results/." "$target"
echo "수집 완료: $target"
