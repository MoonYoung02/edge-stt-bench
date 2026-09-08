#!/usr/bin/env python3
"""Receive EdgeSTT Bench result JSON files over the local network."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_BODY_BYTES = 64 * 1024 * 1024
UPLOAD_PATH = "/api/v1/benchmark-runs"


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:160] or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")


class ResultReceiver(ThreadingHTTPServer):
    output_dir: Path
    bearer_token: str | None


class Handler(BaseHTTPRequestHandler):
    server: ResultReceiver

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") not in {"", "/health"}:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "service": "edge-stt-bench-result-receiver",
                "uploadPath": UPLOAD_PATH,
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].rstrip("/") != UPLOAD_PATH:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0:
            self.send_json(HTTPStatus.LENGTH_REQUIRED, {"ok": False, "error": "Content-Length required"})
            return
        if length > MAX_BODY_BYTES:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "body too large"})
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON root must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
            return

        run_id = safe_name(str(payload.get("runId") or self.headers.get("Idempotency-Key") or ""))
        target = self.server.output_dir / f"{run_id}.json"
        formatted = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.server.output_dir, prefix=f".{run_id}-", delete=False
            ) as temporary:
                temporary.write(formatted)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

        print(f"수신 완료: {target} ({len(formatted):,} bytes)", flush=True)
        self.send_json(
            HTTPStatus.CREATED,
            {"ok": True, "runId": run_id, "file": target.name, "bytes": len(formatted)},
        )

    def authorized(self) -> bool:
        expected = self.server.bearer_token
        if not expected:
            return True
        actual = self.headers.get("Authorization", "")
        return hmac.compare_digest(actual, f"Bearer {expected}")

    def log_message(self, message: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {message % args}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EdgeSTT Bench JSON receiver")
    parser.add_argument("--host", default="0.0.0.0", help="listen address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8787, help="listen port (default: 8787)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("received-benchmark-results"),
        help="result directory (default: ./received-benchmark-results)",
    )
    parser.add_argument("--token", help="optional Bearer token")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    server = ResultReceiver((args.host, args.port), Handler)
    server.output_dir = output_dir
    server.bearer_token = args.token
    print(f"EdgeSTT Bench receiver: http://{args.host}:{args.port}", flush=True)
    print(f"POST {UPLOAD_PATH}", flush=True)
    print(f"저장 위치: {output_dir}", flush=True)
    print("종료: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
