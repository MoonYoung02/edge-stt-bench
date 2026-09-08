"""Isolated pyannote runtime. Executed by .venv-diarization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


MODEL_ID = "pyannote/speaker-diarization-community-1"


def annotation_rows(annotation) -> list[dict]:
    return [
        {
            "start": round(float(turn.start), 6),
            "end": round(float(turn.end), 6),
            "speaker": str(speaker),
        }
        for turn, _track, speaker in annotation.itertracks(yield_label=True)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--speakers", type=int)
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    args = parser.parse_args()

    import torch
    from huggingface_hub import get_token
    from pyannote.audio import Pipeline

    device = args.device
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    token = get_token()
    if not token:
        raise RuntimeError("Hugging Face 로그인이 필요합니다: hf auth login")
    started = time.perf_counter()
    pipeline = Pipeline.from_pretrained(MODEL_ID, token=token)
    pipeline.to(torch.device(device))

    def progress(step_name, artifact, completed=None, total=None, **kwargs):
        if completed is not None and total is not None:
            print(f"DIARIZATION_PROGRESS {int(completed)} {int(total)} {step_name}", flush=True)

    options = {"hook": progress}
    if args.speakers is not None:
        options["num_speakers"] = args.speakers
    output = pipeline(str(args.audio), **options)
    regular = annotation_rows(output.speaker_diarization)
    exclusive = annotation_rows(output.exclusive_speaker_diarization)
    speakers = sorted({row["speaker"] for row in regular})
    payload = {
        "model": MODEL_ID,
        "device": device,
        "seconds": time.perf_counter() - started,
        "speakers": speakers,
        "diarization": regular,
        "exclusive_diarization": exclusive,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
