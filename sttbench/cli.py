"""Public command-line interface."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
sys.dont_write_bytecode = True

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sttbench",
        description="여러 로컬 STT 모델을 같은 형식으로 실행하고 비교하는 도구",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="실행 환경과 등록 모델 상태 확인")
    commands.add_parser("models", help="등록된 모델 목록 확인")
    commands.add_parser("check", help="doctor의 호환 별칭")
    inspect_parser = commands.add_parser(
        "inspect", help="오디오 하나를 전사하고 모든 중간 산출물 저장"
    )
    inspect_parser.add_argument("audio", type=Path, help="WAV, M4A, MP3 등 오디오 파일")
    inspect_parser.add_argument(
        "--model", required=True, help="config/models.yaml의 모델 ID"
    )
    inspect_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps"),
        help="실행 장치(생략하면 모델 설정 사용)",
    )
    inspect_parser.add_argument(
        "--language",
        default="auto",
        help="언어 코드(기본: auto, 한국어 고정은 ko)",
    )
    inspect_parser.add_argument(
        "--diarize",
        action="store_true",
        help="모노 음성에서 pyannote 화자 분리 실행",
    )
    inspect_parser.add_argument(
        "--speakers",
        type=int,
        help="알고 있는 화자 수(지정하면 --diarize 자동 적용)",
    )
    inspect_parser.add_argument(
        "--diarization-device",
        choices=("auto", "mps", "cpu"),
        default="auto",
        help="화자 분리 장치(기본: auto)",
    )
    evaluate_parser = commands.add_parser(
        "evaluate",
        help="KCSC 전체를 전사하고 CER/WER 요약 생성",
    )
    evaluate_parser.add_argument("--dataset", choices=("kcsc",), default="kcsc")
    evaluate_parser.add_argument(
        "--model", required=True, help="config/models.yaml의 모델 ID"
    )
    evaluate_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps"),
        default="auto",
        help="실행 장치(기본: auto)",
    )
    evaluate_parser.add_argument("--language", default="ko", help="언어 코드(기본: ko)")
    evaluate_parser.add_argument("--limit", type=int, help="앞에서 N개만 평가")
    evaluate_parser.add_argument(
        "--resume",
        action="store_true",
        help="같은 모델·장치·언어의 미완료 실행 이어서 진행",
    )
    matrix_parser = commands.add_parser(
        "evaluate-all",
        help="등록 모델을 CPU에서 차례로 KCSC 평가",
    )
    matrix_parser.add_argument("--dataset", choices=("kcsc",), default="kcsc")
    matrix_parser.add_argument(
        "--models",
        nargs="+",
        help="평가할 모델 ID 목록(생략하면 등록된 모든 모델)",
    )
    matrix_parser.add_argument(
        "--devices",
        nargs="+",
        choices=("cpu", "mps"),
        default=("cpu",),
        help="모델별 실행 장치 순서(기본: cpu)",
    )
    matrix_parser.add_argument("--language", default="ko", help="언어 코드(기본: ko)")
    matrix_parser.add_argument(
        "--limit", type=int, help="모델·장치별 앞에서 N개만 평가"
    )
    commands.add_parser("download", help="Hugging Face에서 KCSC 데이터 다운로드")
    commands.add_parser("test", help="기존 Whisper 10개 평가")
    commands.add_parser("run", help="기존 Whisper 전체 평가")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"doctor", "check"}:
            return doctor()
        if args.command == "models":
            return show_models()
        if args.command == "download":
            from sttbench.datasets.kcsc import download_dataset

            download_dataset(PROJECT_ROOT)
            return 0
        if args.command == "inspect":
            from sttbench.runner import inspect_audio

            if args.speakers is not None and args.speakers < 1:
                raise ValueError("--speakers는 1 이상이어야 합니다.")
            inspect_audio(
                PROJECT_ROOT,
                args.audio,
                args.model,
                args.language,
                device=args.device,
                diarize=args.diarize or args.speakers is not None,
                num_speakers=args.speakers,
                diarization_device=args.diarization_device,
            )
            return 0
        if args.command == "evaluate":
            from sttbench.evaluator import evaluate_kcsc

            evaluate_kcsc(
                PROJECT_ROOT,
                args.model,
                device=args.device,
                language=args.language,
                limit=args.limit,
                resume=args.resume,
            )
            return 0
        if args.command == "evaluate-all":
            from sttbench.matrix import evaluate_matrix

            evaluate_matrix(
                PROJECT_ROOT,
                model_ids=args.models,
                devices=args.devices,
                language=args.language,
                limit=args.limit,
            )
            return 0
        return run_legacy(args.command)
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        return 130
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


def doctor() -> int:
    from sttbench.diarization import check_runtime
    from sttbench.registry import ModelRegistry

    print("STT Bench 환경 확인")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    print(f"ffmpeg: {'준비됨' if ffmpeg else '없음'}")
    print(f"ffprobe: {'준비됨' if ffprobe else '없음'}")
    registry = ModelRegistry(PROJECT_ROOT)
    grouped: dict[str, object] = {}
    for spec in registry.list():
        if spec.adapter not in grouped:
            grouped[spec.adapter] = registry.create_adapter(spec.id).check()
    for adapter_name, status in grouped.items():
        print(
            f"{adapter_name}: {'준비됨' if status.ready else '사용 불가'} - {status.detail}"
        )
    diarization_ready, diarization_detail = check_runtime(PROJECT_ROOT)
    print(
        "speaker_diarization: "
        f"{'준비됨' if diarization_ready else '사용 불가'} - {diarization_detail}"
    )
    txt_count = len(list((PROJECT_ROOT / "data" / "kcsc" / "TXT").glob("*.txt")))
    wav_count = len(list((PROJECT_ROOT / "data" / "kcsc" / "WAV").glob("*.wav")))
    print(f"KCSC 데이터: TXT {txt_count}개 / WAV {wav_count}개")
    python_ready = grouped.get("whisper_python")
    return 0 if ffmpeg and ffprobe and python_ready and python_ready.ready else 1


def show_models() -> int:
    from sttbench.registry import ModelRegistry

    registry = ModelRegistry(PROJECT_ROOT)
    print(f"{'MODEL':22} {'ADAPTER':16} {'DEVICE':8} STATUS")
    print("-" * 76)
    for spec in registry.list():
        status = registry.create_adapter(spec.id).check()
        ready = "ready" if status.ready else "unavailable"
        print(
            f"{spec.id:22} {spec.adapter:16} {spec.device:8} {ready} - {status.detail}"
        )
    return 0


def run_legacy(command: str) -> int:
    try:
        from evaluator import evaluate
    except ImportError as exc:
        raise RuntimeError("기존 evaluator.py를 찾을 수 없습니다.") from exc
    if command == "test":
        evaluate(test_mode=True)
    elif command == "run":
        evaluate(test_mode=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
