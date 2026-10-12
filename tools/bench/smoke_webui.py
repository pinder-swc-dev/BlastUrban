#!/usr/bin/env python3
"""Guarded WebUI -> SSH -> Docker smoke test. This never runs CFD commands."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


WORKSPACE = Path("/tmp/BlastUrban-smoke-20261002-final")
TRASH = Path.home() / ".Trash/BlastUrban-smoke-20261002-final"
NAMES = {
    "success": "blasturban-webui-smoke-20261002-success",
    "exit3": "blasturban-webui-smoke-20261002-exit3",
    "aborted": "blasturban-webui-smoke-20261002-aborted",
    "stopped": "blasturban-webui-smoke-20261002-stopped",
}
MARKER = "SMOKE TEST — NOT CFD"


def guarded_script(body: str) -> str:
    return """#!/usr/bin/env bash
set -Eeuo pipefail
source ./smoke.env
[[ ${BLASTURBAN_SMOKE_TEST:-0} == 1 ]] || {
    printf 'SMOKE GUARD MISSING\\n' >&2
    exit 64
}
""" + body


def build_fixtures(repo: Path) -> dict[str, Path]:
    sys.path.insert(0, str(repo / "tools/blast_case_ui"))
    from blast_case_builder import CaseConfig, create_case

    case_root = WORKSPACE / "cases"
    case_root.mkdir(parents=True, exist_ok=False)
    stl = repo / "tutorials/blastFoam/building3DWorkshop/constant/triSurface/townBuildings.stl"
    cases: dict[str, Path] = {}
    for mode, name in NAMES.items():
        case, _, _ = create_case(
            CaseConfig(case_name=name, stl_path=str(stl), mpi_ranks=1),
            case_root,
            create_archive=False,
        )
        (case / "smoke.env").write_text("BLASTURBAN_SMOKE_TEST=1\n", encoding="utf-8")
        (case / "preflight.sh").write_text(
            guarded_script(
                "command -v blastFoam >/dev/null\n"
                "blast_path=$(command -v blastFoam)\n"
                "[[ -f $blast_path && -x $blast_path ]] || exit 4\n"
                "blastFoam -help >/dev/null\n"
                f"printf '{MARKER} — PREFLIGHT\\n'\n"
            ),
            encoding="utf-8",
        )
        allrun_tail = ""
        if mode == "exit3":
            allrun_tail = "exit 3\n"
        else:
            allrun_tail = "printf 'container smoke pass\\n' > smoke-container-pass.txt\n"
        (case / "Allrun").write_text(
            guarded_script(
                f"printf '{MARKER}\\n'\n"
                "grep numberOfSubdomains system/decomposeParDict\n"
                "sleep 6\n"
                + allrun_tail
            ),
            encoding="utf-8",
        )
        html = (
            '<!doctype html><html lang="th"><meta charset="utf-8">'
            '<title>BlastUrban smoke result</title>'
            f'<body><p id="smoke-marker">{MARKER}</p>'
            '<p>ไม่ใช่ผลการคำนวณ CFD</p></body></html>\n'
        )
        escaped = html.replace("'", "'\\''")
        (case / "makeWebResults.sh").write_text(
            guarded_script(
                "mkdir -p results-web\n"
                f"printf '%s' '{escaped}' > results-web/blast3D.html\n"
                f"printf '{MARKER} — WEB RESULT\\n'\n"
            ),
            encoding="utf-8",
        )
        for script in ("preflight.sh", "Allrun", "makeWebResults.sh"):
            (case / script).chmod(0o755)
        cases[mode] = case
    return cases


class Client:
    def __init__(self, base: str, common: dict[str, object]):
        self.base = base
        self.common = common

    def post(self, path: str, extra: dict[str, object] | None = None, expect_error: bool = False):
        payload = dict(self.common)
        payload.update(extra or {})
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                result = json.load(response)
            if expect_error:
                raise AssertionError(f"{path} unexpectedly succeeded")
            return result
        except urllib.error.HTTPError as exc:
            detail = json.loads(exc.read().decode("utf-8"))
            if not expect_error:
                raise RuntimeError(f"{path}: {detail}") from exc
            return detail


def wait_state(client: Client, name: str, terminal: bool, timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        result = client.post("/api/server/status", {"server_case_name": name})
        status = result["status"]
        state = str(status.get("state", ""))
        if not seen or seen[-1] != state:
            seen.append(state)
        if terminal and state in {"complete", "failed", "viewer_failed", "stopped"}:
            return status, seen
        if not terminal and state in {"running", "postprocessing"}:
            return status, seen
        time.sleep(0.5)
    raise TimeoutError(f"{name}: timed out; states={seen}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-confirmed", action="store_true")
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    if not args.cleanup_confirmed:
        raise SystemExit("Refusing: pass --cleanup-confirmed only after the user confirms group A")
    if WORKSPACE.exists() or TRASH.exists():
        raise SystemExit(f"Smoke path already exists: {WORKSPACE} or {TRASH}")

    repo = Path(__file__).resolve().parents[2]
    os.environ["BLASTURBAN_WORKSPACE"] = str(WORKSPACE)
    os.environ["BLASTURBAN_IMAGE_READY_CACHE"] = "1"
    cases = build_fixtures(repo)
    (WORKSPACE / "results").mkdir()

    from blast_case_web import HOST, Handler, STATE, ThreadingHTTPServer, _run_remote

    connection = (
        args.host, args.user, args.port, args.key.expanduser().resolve(),
    )
    common: dict[str, object] = {
        "server_host": connection[0],
        "server_user": connection[1],
        "server_port": connection[2],
        "ssh_key": str(connection[3]),
        "remote_root": args.remote_root,
        "docker_image": args.image,
        "docker_platform": "linux/amd64",
        "server_core_mode": "manual",
        "server_cores": 1,
        "server_memory": 2,
        "fetch_output": str(WORKSPACE / "results"),
        "accept_no_linger": True,
    }
    server = ThreadingHTTPServer((HOST, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://{HOST}:{server.server_address[1]}", common)
    report: dict[str, object] = {"marker": MARKER, "jobs": {}, "cleanup": []}
    submitted: list[str] = []
    try:
        report["connection"] = client.post("/api/server/test-connection")
        started = time.perf_counter()
        first_check = client.post("/api/server/check")
        first_seconds = time.perf_counter() - started
        started = time.perf_counter()
        second_check = client.post("/api/server/check")
        second_seconds = time.perf_counter() - started
        assert first_check["linger"] == "no"
        assert first_check["image_check"]["ok"] is True
        assert second_check["image_check"]["cache_hit"] is True
        report["readiness"] = {
            "first_seconds": round(first_seconds, 6),
            "second_seconds": round(second_seconds, 6),
            "first_cache_hit": first_check["image_check"]["cache_hit"],
            "second_cache_hit": second_check["image_check"]["cache_hit"],
            "image_id": second_check["image_check"]["image_id"],
        }

        def submit(mode: str):
            name = NAMES[mode]
            result = client.post("/api/server/submit", {
                "local_case_path": str(cases[mode]),
                "server_case_name": name,
            })
            assert result["case_name"] == name
            submitted.append(name)
            return result

        success_submit = submit("success")
        duplicate = client.post("/api/server/submit", {
            "local_case_path": str(cases["success"]),
            "server_case_name": NAMES["success"],
        }, expect_error=True)
        assert "ปฏิเสธการส่งซ้ำ" in duplicate["error"]
        success_status, success_seen = wait_state(client, NAMES["success"], terminal=True)
        assert success_status["state"] == "complete", success_status
        assert success_status["accept_no_linger"] is True
        assert success_status["linger"] == "no"
        assert success_status["docker_exit_code"] == 0
        assert success_status["oom_killed"] is False
        assert success_status["systemd"]["result"] == "success"
        assert success_status["systemd"]["exec_main_status"] == "0"
        logs = client.post("/api/server/logs", {"server_case_name": NAMES["success"]})["logs"]
        assert MARKER in logs
        fetched = client.post("/api/server/fetch", {"server_case_name": NAMES["success"]})
        with urllib.request.urlopen(client.base + fetched["viewer_url"], timeout=30) as response:
            viewer = response.read().decode("utf-8")
        assert 'id="smoke-marker"' in viewer and MARKER in viewer and "ไม่ใช่ผลการคำนวณ CFD" in viewer
        assert "<canvas" not in viewer.lower()
        report["jobs"]["success"] = {
            "submit": success_submit,
            "states": success_seen,
            "status": success_status,
            "duplicate_error": duplicate["error"],
            "viewer_http": 200,
            "viewer_marker": True,
        }

        submit("exit3")
        exit_status, exit_seen = wait_state(client, NAMES["exit3"], terminal=True)
        assert exit_status["state"] == "failed" and exit_status["docker_exit_code"] == 3
        failed_fetch = client.post("/api/server/fetch", {
            "server_case_name": NAMES["exit3"],
        }, expect_error=True)
        report["jobs"]["exit3"] = {
            "states": exit_seen, "status": exit_status,
            "fetch_error": failed_fetch["error"],
        }

        aborted_submit = submit("aborted")
        _, aborted_seen_running = wait_state(client, NAMES["aborted"], terminal=False)
        unit = aborted_submit["unit"]
        _run_remote(
            connection,
            'systemctl --user kill --kill-whom=main --signal=SIGKILL "$1"',
            (unit,),
            timeout=30,
        )
        aborted_status, aborted_seen_terminal = wait_state(
            client, NAMES["aborted"], terminal=True, timeout=20
        )
        assert aborted_status["state"] == "failed"
        assert aborted_status["failure"] == "runner_aborted"
        report["jobs"]["aborted"] = {
            "states": aborted_seen_running + aborted_seen_terminal,
            "status": aborted_status,
        }

        submit("stopped")
        _, stopped_seen_running = wait_state(client, NAMES["stopped"], terminal=False)
        running_fetch = client.post("/api/server/fetch", {
            "server_case_name": NAMES["stopped"],
        }, expect_error=True)
        client.post("/api/server/stop", {"server_case_name": NAMES["stopped"]})
        stopped_status, stopped_seen_terminal = wait_state(
            client, NAMES["stopped"], terminal=True, timeout=20
        )
        assert stopped_status["state"] == "stopped"
        stopped_fetch = client.post("/api/server/fetch", {
            "server_case_name": NAMES["stopped"],
        }, expect_error=True)
        report["jobs"]["stopped"] = {
            "states": stopped_seen_running + stopped_seen_terminal,
            "status": stopped_status,
            "running_fetch_error": running_fetch["error"],
            "stopped_fetch_error": stopped_fetch["error"],
        }

        remote_evidence = _run_remote(
            connection,
            r'''
set -eu
root=$1
shift
python3 - "$root" "$@" <<'PY'
import json, os, subprocess, sys
root, *names = sys.argv[1:]
out = {}
for name in names:
    case = os.path.join(root, name)
    def load(filename):
        try:
            with open(os.path.join(case, filename), encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            return {}
    status = load("server-job-status.json")
    recorded = load("server-job-unit-result.json")
    unit = status.get("unit", "")
    shown = {}
    if unit:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ExecMainStatus", "-p", "ActiveState"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        shown = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    journal = ""
    if unit:
        journal = subprocess.run(
            ["journalctl", "--user", "-u", unit, "--no-pager", "-o", "cat"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        ).stdout
    out[name] = {
        "status": status, "unit_result": recorded, "systemd": shown,
        "forbidden_journal_tokens": [token for token in ("clear_console", "unbound variable", "bash_logout") if token in journal],
    }
leftovers = subprocess.run(
    ["docker", "ps", "-a", "--filter", "name=blasturban", "--format", "{{.Names}}"],
    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
).stdout.splitlines()
out["_leftover_non_build_containers"] = [name for name in leftovers if not name.startswith("blasturban-build-")]
print(json.dumps(out, ensure_ascii=False))
PY
''',
            (common["remote_root"], *NAMES.values()),
            timeout=60,
        )
        evidence = json.loads(remote_evidence.stdout)
        assert not evidence.pop("_leftover_non_build_containers")
        assert all(not item["forbidden_journal_tokens"] for item in evidence.values())
        assert evidence[NAMES["success"]]["unit_result"]["service_result"] == "success"
        assert evidence[NAMES["success"]]["systemd"]["Result"] == "success"
        assert evidence[NAMES["success"]]["systemd"]["ExecMainStatus"] == "0"
        report["remote_evidence"] = evidence
    finally:
        for name in reversed(submitted):
            try:
                result = client.post("/api/server/delete-job", {
                    "server_case_name": name,
                    "cleanup_case_name": name,
                })
                report["cleanup"].append(result)
            except Exception as exc:  # retain exact diagnostics in the report
                report["cleanup"].append({"job": name, "error": str(exc)})
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        STATE.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if WORKSPACE.exists():
            TRASH.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(WORKSPACE), str(TRASH))


if __name__ == "__main__":
    main()
