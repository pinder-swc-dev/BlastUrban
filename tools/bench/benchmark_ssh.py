#!/usr/bin/env python3
"""Measure BlastUrban SSH call overhead without running CFD or Docker."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


def timed(command: list[str]) -> float:
    started = time.perf_counter()
    result = subprocess.run(
        command + ["true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-1000:])
    return elapsed


def summary(samples: list[float]) -> dict[str, float | int]:
    return {
        "calls": len(samples),
        "total_seconds": round(sum(samples), 6),
        "mean_seconds": round(statistics.mean(samples), 6),
        "median_seconds": round(statistics.median(samples), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--iterations", type=int, default=6)
    args = parser.parse_args()
    if not args.key.expanduser().is_file():
        raise SystemExit("SSH key not found")
    if not 2 <= args.iterations <= 50:
        raise SystemExit("iterations must be between 2 and 50")

    destination = f"{args.user}@{args.host}"
    base = [
        "ssh", "-i", str(args.key.expanduser()), "-p", str(args.port),
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    direct = [timed(base + [destination]) for _ in range(args.iterations)]

    with tempfile.TemporaryDirectory(prefix="blasturban-ssh-bench-") as directory:
        control = str(Path(directory) / "cm")
        multiplexed_command = base + [
            "-o", "ControlMaster=auto", "-o", "ControlPersist=60",
            "-o", f"ControlPath={control}", destination,
        ]
        # The first call includes master establishment; report it separately
        # and compare steady-state calls with independent connections.
        first = timed(multiplexed_command)
        reused = [timed(multiplexed_command) for _ in range(args.iterations)]
        subprocess.run(
            base + ["-S", control, "-O", "exit", destination],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )

    print(json.dumps({
        "command": "remote true (no Docker, no CFD)",
        "direct": summary(direct),
        "multiplex_master_seconds": round(first, 6),
        "multiplex_reused": summary(reused),
    }, indent=2))


if __name__ == "__main__":
    main()
