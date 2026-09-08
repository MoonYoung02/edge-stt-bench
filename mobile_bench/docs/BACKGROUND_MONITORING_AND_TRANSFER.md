# 백그라운드 실행, 계측 및 결과 전송

## 구현 범위

벤치마크 실행은 Flutter 화면 수명과 분리된 `BenchmarkCoordinator`가 관리합니다.
실행을 시작하면 결과 JSON을 먼저 `running` 상태로 저장하고, 500ms 간격으로 시스템
지표를 모읍니다. 수집 중인 sample은 5초마다 같은 JSON에 checkpoint하고 완료·실패·
취소 시 최종 갱신합니다. 앱이 비정상 종료된 경우 다음 실행에서 남은 `running`
결과를 `interrupted`로 변경합니다.

```text
사용자 실행
  → running JSON 저장
  → OS 백그라운드 실행 권한 확보
  → 500ms telemetry 수집 + STT 추론
  → completed / failed / cancelled JSON 저장
  → 결과 그래프 / 서버 업로드 / 파일 내보내기
```

## 실시간 지표

| 지표 | Android 측정값 |
|---|---|
| 앱 CPU | 프로세스 누적 CPU 시간의 구간 차이 |
| 앱 RAM | 프로세스 PSS |
| native heap | `Debug.getNativeHeapAllocatedSize` |
| 발열 상태 | `PowerManager.currentThermalStatus` |
| thermal headroom | Android 11+ `getThermalHeadroom` |
| 배터리 온도 | 배터리 브로드캐스트 값 |
| 화면 상태 | `PowerManager.isInteractive` |

CPU의 `cpuCoreEquivalentPercent`는 코어 하나를 100%로 계산하므로 멀티코어 작업은
100%를 넘을 수 있습니다. `cpuDeviceNormalizedPercent`는 논리 코어 수로 나눈
0~100% 값입니다. 결과 화면은 평균/최대 CPU, 평균/Peak RAM, 최고 발열 상태와
시간축 그래프를 표시합니다. 화면 상태 전환 시점은 그래프 세로선으로 남깁니다.

## Android 백그라운드 실행

- Android 15 이상은 `mediaProcessing` foreground service를 사용합니다.
- Android 14는 `specialUse` foreground service를 사용합니다.
- 더 낮은 버전도 일반 foreground service로 실행합니다.
- 진행률과 취소 버튼이 있는 지속 알림을 표시합니다.
- 6시간 제한의 partial wake lock으로 화면이 꺼진 동안 CPU가 잠들지 않게 합니다.
- 최근 앱 화면에서 앱을 밀어내도 서비스와 Flutter engine을 유지합니다.

사용자가 Android 설정에서 앱을 강제 중지하거나 Android 13+의 Active apps에서
`Stop`을 누르면 OS가 프로세스 전체를 종료하므로 계속 실행할 수 없습니다. 재부팅이나
저메모리로 프로세스 자체가 종료된 작업도 자동 재개하지 않고 `interrupted`로
보존합니다.

## 결과 저장 및 전송

앱 내부 결과는 Application Support의 `results/<runId>.json`에 저장됩니다. JSON에는
기기, 모델, 오디오, 실행 상태, transcript, timing과 전체 telemetry sample이
포함됩니다.

### 등록 서버로 전송

상단의 서버 관리 화면에서 다음 값을 등록합니다.

- 표시 이름
- HTTPS base URL 또는 개발용 사설망 HTTP URL
- POST endpoint (기본 `/api/v1/benchmark-runs`)
- 선택적 Bearer token

token은 플랫폼 secure storage에만 저장하며 서버 목록 JSON이나 벤치마크 결과에
기록하지 않습니다. 결과 화면의 클라우드 버튼은 선택한 서버에 결과 JSON을 POST하고
`Idempotency-Key: <runId>`를 보냅니다. 서버는 2xx로 응답해야 성공으로 처리됩니다.

Mac에서 간단히 결과를 받으려면 다음 서버를 실행합니다.

```bash
cd mobile_bench
./tools/result_receiver.py --port 8787 --output ./received-benchmark-results
```

같은 Wi-Fi에서는 `http://<Mac 사설 IP>:8787`을 앱 Base URL로 사용합니다. USB
디버깅 연결에서는 `adb reverse tcp:8787 tcp:8787`을 실행한 뒤 앱에
`http://127.0.0.1:8787`을 등록할 수 있습니다. 두 방식의 endpoint는 모두
`/api/v1/benchmark-runs`입니다. 평문 HTTP에서는 Bearer token을 입력하지 말고,
외부 네트워크나 운영 서버에는 HTTPS를 사용합니다.

### USB/ADB로 전송

Mac에서 다음을 실행합니다. 디버그 빌드는 `run-as`로 앱 내부 결과를 직접
스트리밍하므로 내보내기 버튼을 누를 필요가 없습니다.

```bash
cd mobile_bench
./tools/pull_benchmark_results.sh R3CRC0LMBTJ ./benchmark-results
```

서명된 release 빌드는 보통 `run-as`를 허용하지 않습니다. 이때는 결과 화면의
내보내기 버튼으로 `Download/STTBench/results`에 복사한 뒤 같은 스크립트를 실행하면
공용 폴더에서 가져옵니다.

새 결과를 반복 수집하려면 다음 스크립트를 사용합니다.

```bash
./tools/watch_benchmark_results.sh R3CRC0LMBTJ ./benchmark-results
```

## 검증 체크리스트

1. 5분 이상 걸리는 sample로 벤치마크를 시작한다.
2. 진행 중 CPU/RAM/발열 값과 알림 진행률이 바뀌는지 확인한다.
3. 화면을 끄고 2분 뒤 다시 켜 진행률이 이어지는지 확인한다.
4. Android에서는 최근 앱 화면에서 앱을 밀어낸 뒤 알림이 유지되는지 확인한다.
5. 완료 후 그래프에 screen state 전환선과 Peak RAM이 있는지 확인한다.
6. 결과 내보내기 후 pull 스크립트로 JSON을 Mac에 수집한다.
7. 테스트 서버에 업로드해 body와 `Idempotency-Key`를 확인한다.
