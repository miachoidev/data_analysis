#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("[RUN]", " ".join(cmd))
    res = subprocess.run(cmd, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd)}")


def main() -> None:
    p = argparse.ArgumentParser(description="5~9 분석 스크립트 일괄 실행")
    p.add_argument("--profile-file", required=True)
    p.add_argument("--chat-file", required=True)
    p.add_argument("--ai-transfer-file", default=None)
    p.add_argument("--event-file", default=None)
    p.add_argument("--output-dir", default="output_5to9_refactor")
    args = p.parse_args()

    here = Path(__file__).parent
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    py = sys.executable

    run(
        [
            py,
            str(here / "a01_signup_alignment.py"),
            "--profile-file",
            args.profile_file,
            "--event-file",
            args.event_file or "",
            "--output-dir",
            str(out),
        ]
    )
    run(
        [
            py,
            str(here / "a02_transfer_prepost.py"),
            "--profile-file",
            args.profile_file,
            "--chat-file",
            args.chat_file,
            "--ai-transfer-file",
            args.ai_transfer_file or "",
            "--output-dir",
            str(out),
        ]
    )
    run(
        [
            py,
            str(here / "a03_reuse_rate.py"),
            "--profile-file",
            args.profile_file,
            "--chat-file",
            args.chat_file,
            "--output-dir",
            str(out),
        ]
    )
    run(
        [
            py,
            str(here / "a04_reuser_characteristics.py"),
            "--profile-file",
            args.profile_file,
            "--chat-file",
            args.chat_file,
            "--out-dir",
            str(out),
        ]
    )
    run(
        [
            py,
            str(here / "a05_nonreuse_causes.py"),
            "--profile-file",
            args.profile_file,
            "--chat-file",
            args.chat_file,
            "--output-dir",
            str(out),
        ]
    )
    print(f"[DONE] 5~9 분석 완료: {out.resolve()}")


if __name__ == "__main__":
    main()
