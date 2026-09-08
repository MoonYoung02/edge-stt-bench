#!/usr/bin/env python3
"""Compatibility entry point; the implementation lives in sttbench."""

from sttbench.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
