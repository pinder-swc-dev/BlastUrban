#!/usr/bin/env python3
"""Dependency-free localhost web UI for the BlastUrban case builder.

This front end avoids the system Tk 8.5 framework shipped with Apple's
Command Line Tools, which cannot create windows on some macOS 26 releases.
The HTTP server binds to 127.0.0.1 only and never exposes itself to the LAN.
"""

from __future__ import annotations

import json
import errno
import math
import os
import pty
import re
import select
import secrets
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from blast_case_builder import (
    DEFAULT_TEMPLATE,
    Bounds,
    CaseConfig,
    StlReport,
    analyse_stl,
    auto_charge_level,
    auto_domain,
    auto_surface_levels,
    create_case,
    iter_stl_triangles,
    mesh_divisions,
    parse_probes,
    point_surface_relation,
    repair_stl,
    safe_case_name,
    validate_config,
)


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = Path(__file__).with_name("web") / "index.html"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
DEFAULT_SSH_KEY = Path.home() / ".ssh/blasturban_ed25519"
DEFAULT_WORKSPACE = Path(
    os.environ.get("BLASTURBAN_WORKSPACE", str(Path.home() / "BlastUrbanWorkspace"))
).expanduser().resolve()
REQUIRED_EXECUTABLES = (
    "surfaceCheck surfaceFeatures blockMesh checkMesh decomposePar snappyHexMesh "
    "addEmptyPatch setRefinedFields blastFoam blastToVTK calculateImpulse mpirun"
)
# Image readiness runs through plain `bash -c`.  A login shell (`bash -lc`)
# executes ~/.bash_logout on an explicit exit; Ubuntu's clear_console fails
# without a terminal and turns a successful check into status 1.
# Exit codes: 0 ready, 2 missing executables, 3 Python VTK missing,
# 4 blastFoam present but unable to execute.
IMAGE_READY_CHECK = f"""set +e
for f in /opt/openfoam9/etc/bashrc /root/OpenFOAM/OpenFOAM-9/etc/bashrc /root/OpenFOAM/OpenFOAM-v9/etc/bashrc; do
    if [ -f "$f" ]; then . "$f" >/dev/null 2>&1; break; fi
done
for f in /opt/blastfoam/etc/bashrc /opt/BlastUrban/etc/bashrc /workspace/BlastUrban/etc/bashrc /root/OpenFOAM/blastfoam/etc/bashrc; do
    if [ -f "$f" ]; then . "$f" >/dev/null 2>&1; break; fi
done
missing=""
for command in {REQUIRED_EXECUTABLES}; do
    command -v "$command" >/dev/null 2>&1 || missing="$missing $command"
done
if [ -n "$missing" ]; then echo "missing executables:$missing" >&2; exit 2; fi
# command -v only proves a path exists; running the solver also catches
# missing shared libraries, a wrong architecture, or a broken environment.
if ! blastFoam -help >/dev/null 2>&1; then
    echo "blastFoam is on PATH but cannot execute (libraries, architecture, or environment)" >&2
    exit 4
fi
if /usr/bin/python3 -c 'import vtk' >/dev/null 2>&1 || python3 -c 'import vtk' >/dev/null 2>&1; then exit 0; fi
echo "Python VTK is missing" >&2
exit 3
"""


class AppState:
    def __init__(self) -> None:
        # User models, generated cases and downloaded results stay outside the
        # blastFoam source tree.  Paths below /Users are mountable by Docker
        # Desktop on macOS while keeping the repository uncluttered.
        runtime_parent = DEFAULT_WORKSPACE / "temp"
        runtime_parent.mkdir(parents=True, exist_ok=True)
        stale_before = time.time() - 7 * 86400
        for candidate in runtime_parent.glob(".ui-work-*"):
            try:
                if not candidate.is_dir() or candidate.stat().st_mtime >= stale_before:
                    continue
                owner_path = candidate / ".owner.json"
                owner = json.loads(owner_path.read_text(encoding="utf-8")) if owner_path.is_file() else {}
                owner_pid = int(owner.get("pid", 0))
                if owner_pid:
                    try:
                        os.kill(owner_pid, 0)
                        continue
                    except (OSError, ProcessLookupError):
                        pass
                shutil.rmtree(candidate)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                # Temporary cleanup must never prevent the UI from starting.
                pass
        self.upload_dir = Path(tempfile.mkdtemp(prefix=".ui-work-", dir=runtime_parent))
        (self.upload_dir / ".owner.json").write_text(
            json.dumps({"pid": os.getpid(), "created": time.time()}) + "\n",
            encoding="utf-8",
        )
        self.reports: Dict[Tuple[str, float], StlReport] = {}
        self.result_viewers: Dict[str, Path] = {}
        self.lock = threading.Lock()

    def close(self) -> None:
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def report(self, path: Path, scale: float, external: bool) -> StlReport:
        resolved = str(path.expanduser().resolve())
        key = (resolved, scale)
        with self.lock:
            cached = self.reports.get(key)
        if cached is not None and (not external or cached.external_returncode is not None):
            return cached
        report = analyse_stl(Path(resolved), scale, run_external=external)
        with self.lock:
            self.reports[key] = report
        return report

    def forget_reports_for(self, path: Path) -> None:
        """Discard cached checks after the contents at a path have changed."""
        resolved = str(path.expanduser().resolve())
        with self.lock:
            stale = [key for key in self.reports if key[0] == resolved]
            for key in stale:
                del self.reports[key]

    def register_result_viewer(self, path: Path) -> str:
        """Expose one generated, self-contained viewer through localhost."""
        resolved = path.expanduser().resolve()
        if not resolved.is_file() or resolved.suffix.lower() != ".html":
            raise ValueError("ไม่พบไฟล์ผลลัพธ์ 3D ที่ดึงกลับมา")
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.result_viewers[token] = resolved
        return token

    def result_viewer(self, token: str) -> Optional[Path]:
        with self.lock:
            return self.result_viewers.get(token)


STATE = AppState()


def _is_managed_upload(path: Path) -> bool:
    """Return true only for the disposable copy uploaded through this Web UI."""
    try:
        path.expanduser().resolve().relative_to(STATE.upload_dir.resolve())
        return True
    except ValueError:
        return False


# Files a generated case must contain before it may be sent to a server.  The
# same list is re-checked on the server after rsync.
REQUIRED_CASE_FILES = (
    "case-builder.json",
    "server-docker-job.sh",
    "makeWebResults.sh",
    "preflight.sh",
    "Allrun",
    "organizeSurfaceCheckOutput.sh",
    "system/controlDict",
    "system/blockMeshDict",
    "system/snappyHexMeshDict",
    "system/surfaceFeaturesDict",
    "system/decomposeParDict",
    "system/setFieldsDict",
    "system/fvSchemes",
    "system/fvSolution",
    "constant/phaseProperties",
    "constant/dynamicMeshDict",
    "visualization/exportBlast3D.py",
    "visualization/viewer_template.html",
)


def missing_case_files(case: Path) -> list[str]:
    """Return required inputs that are absent from a generated case folder."""
    missing = [name for name in REQUIRED_CASE_FILES if not (case / name).is_file()]
    if not any((case / "constant/triSurface").glob("*.stl")):
        missing.append("constant/triSurface/*.stl")
    if not any((case / "0").glob("*.orig")):
        missing.append("0/*.orig")
    return missing


def local_case_records(parent: Path) -> list[Dict[str, Any]]:
    """List generated cases immediately below one user-selected directory."""
    parent = Path(parent).expanduser().resolve()
    if not parent.is_dir():
        return []
    records: list[Dict[str, Any]] = []
    try:
        candidates = list(parent.iterdir())
    except OSError:
        return []
    for candidate in candidates:
        manifest = candidate / "case-builder.json"
        runner = candidate / "server-docker-job.sh"
        if candidate.is_symlink() or not candidate.is_dir() or not manifest.is_file() or not runner.is_file():
            continue
        config: Dict[str, Any] = {}
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("config"), dict):
                config = value["config"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        try:
            stat = manifest.stat()
        except OSError:
            continue
        records.append(
            {
                "name": candidate.name,
                "path": str(candidate),
                "updated_epoch": stat.st_mtime,
                "configured_name": str(config.get("case_name", candidate.name)),
                "charge_mass": config.get("charge_mass"),
                "end_time": config.get("end_time"),
                "mpi_ranks": config.get("mpi_ranks"),
            }
        )
    records.sort(key=lambda item: (item["updated_epoch"], item["name"]), reverse=True)
    return records


def _server_connection(data: Dict[str, Any]) -> Tuple[str, str, int, Path]:
    host = str(data.get("server_host", "")).strip()
    user = str(data.get("server_user", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise ValueError("IP/hostname ของ Server ไม่ถูกต้อง")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", user):
        raise ValueError("ชื่อผู้ใช้ Server ไม่ถูกต้อง")
    try:
        port = int(data.get("server_port", 22))
    except (TypeError, ValueError) as exc:
        raise ValueError("SSH port ต้องเป็นตัวเลข") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SSH port ต้องอยู่ระหว่าง 1–65535")
    key = Path(str(data.get("ssh_key", DEFAULT_SSH_KEY))).expanduser().resolve()
    return host, user, port, key


def _remote_root(data: Dict[str, Any]) -> PurePosixPath:
    text = str(data.get("remote_root", "")).strip()
    path = PurePosixPath(text)
    if (
        not text.startswith("/")
        or ".." in path.parts
        or not re.fullmatch(r"/[A-Za-z0-9_./-]+", text)
    ):
        raise ValueError("Remote work folder ต้องเป็น absolute path และห้ามมี ..")
    return path


def _ssh_args(host: str, user: str, port: int, key: Path) -> list[str]:
    if not key.is_file():
        raise ValueError(f"ยังไม่มี SSH key: {key}; กด ‘ติดตั้ง SSH Key’ ก่อน")
    return [
        "ssh",
        "-i",
        str(key),
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=12",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
    ]


def _run_remote(
    connection: Tuple[str, str, int, Path], script: str, arguments: Tuple[str, ...] = (), timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    command = _ssh_args(*connection)
    remote_command = "bash -s --" + "".join(" " + shlex.quote(value) for value in arguments)
    process = subprocess.run(
        command + [remote_command],
        input=script,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip()
        raise ValueError(f"คำสั่งบน Server ไม่สำเร็จ ({process.returncode}): {detail[-2000:]}")
    return process


def _run_password_pty(command: list[str], password: str, timeout: int = 45) -> str:
    """Run ssh-copy-id with a password kept only in this process and a PTY."""
    if not password or "\n" in password or "\r" in password:
        raise ValueError("กรุณาใส่ password ของ Server")
    master, slave = pty.openpty()
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    output = bytearray()
    sent_password = False
    accepted_host = False
    started = time.monotonic()
    try:
        while process.poll() is None:
            if time.monotonic() - started > timeout:
                process.terminate()
                raise ValueError("ติดตั้ง SSH key ใช้เวลานานเกินกำหนด")
            readable, _, _ = select.select([master], [], [], 0.25)
            if not readable:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            output.extend(chunk)
            recent = bytes(output[-2000:]).lower()
            if b"continue connecting" in recent and not accepted_host:
                os.write(master, b"yes\n")
                accepted_host = True
                output.extend(b"\n")
            if b"password:" in recent and not sent_password:
                os.write(master, password.encode("utf-8") + b"\n")
                sent_password = True
                output.extend(b"\n")
        code = process.wait(timeout=5)
    finally:
        os.close(master)
    readable_output = output.decode("utf-8", errors="replace")
    if code:
        raise ValueError("ติดตั้ง SSH key ไม่สำเร็จ: " + readable_output[-2000:])
    return readable_output


def _number(data: Dict[str, Any], name: str) -> float:
    try:
        value = float(data[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{name}: ต้องเป็นตัวเลข") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name}: ต้องเป็นตัวเลข finite")
    return value


def _integer(data: Dict[str, Any], name: str) -> int:
    try:
        return int(str(data[name]).replace(",", ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{name}: ต้องเป็นจำนวนเต็ม") from exc


def _vec(data: Dict[str, Any], prefix: str) -> Tuple[float, float, float]:
    return (_number(data, prefix + "_x"), _number(data, prefix + "_y"), _number(data, prefix + "_z"))


def payload_to_config(data: Dict[str, Any]) -> CaseConfig:
    return CaseConfig(
        case_name=str(data.get("case_name", "urbanBlast3D")),
        stl_path=str(data.get("stl_path", "")),
        stl_scale=_number(data, "scale"),
        domain_min=(_number(data, "xmin"), _number(data, "ymin"), _number(data, "zmin")),
        domain_max=(_number(data, "xmax"), _number(data, "ymax"), _number(data, "zmax")),
        divisions=(_integer(data, "nx"), _integer(data, "ny"), _integer(data, "nz")),
        surface_min_level=_integer(data, "surface_min"),
        surface_max_level=_integer(data, "surface_max"),
        feature_level=_integer(data, "feature_level"),
        snappy_max_cells=_integer(data, "snappy_cells"),
        dynamic_max_cells=_integer(data, "dynamic_cells"),
        dynamic_max_refinement=_integer(data, "dynamic_levels"),
        refine_interval=_integer(data, "refine_interval"),
        location_in_mesh=_vec(data, "location"),
        charge_centre=_vec(data, "charge"),
        charge_mass=_number(data, "mass"),
        explosive_density=_number(data, "density"),
        charge_refinement_level=_integer(data, "charge_level"),
        probes=parse_probes(str(data.get("probes", ""))),
        plane_point=_vec(data, "plane"),
        end_time=_number(data, "end_time"),
        initial_delta_t=_number(data, "delta_t"),
        max_delta_t=_number(data, "max_delta_t"),
        max_co=_number(data, "max_co"),
        write_interval=_number(data, "write_interval"),
        ambient_pressure=_number(data, "ambient_pressure"),
        pressure_iso_value=_number(data, "iso_pressure"),
        mpi_ranks=_integer(data, "mpi"),
        output_binary=bool(data.get("binary", True)),
        allow_surface_errors=bool(data.get("allow_surface_errors", False)),
    )


def report_payload(report: StlReport) -> Dict[str, Any]:
    span = report.bounds.span
    if report.errors:
        status = "พบจุดที่ควรซ่อมก่อนสร้าง Mesh"
    elif report.warnings:
        status = "ใช้งานได้ แต่มีคำแนะนำให้ตรวจเพิ่ม"
    else:
        status = "โมเดลพร้อมใช้งาน"
    open_edges = report.open_edges if report.open_edges is not None else -1
    non_manifold = report.non_manifold_edges if report.non_manifold_edges is not None else -1
    friendly = "\n".join(
        [
            f"ผลตรวจ: {status}",
            f"ขนาดโมเดล: {span[0]:.4g} × {span[1]:.4g} × {span[2]:.4g} เมตร",
            f"จำนวนผิวสามเหลี่ยม: {report.triangles:,}",
            f"ขอบที่ยังขาด/เป็นรู: {open_edges:,}" if open_edges >= 0 else "ขอบที่ยังขาด/เป็นรู: โมเดลใหญ่ ให้ตรวจซ้ำบน Server",
            f"ขอบที่เชื่อมซ้อนผิดปกติ: {non_manifold:,}" if non_manifold >= 0 else "ขอบที่เชื่อมซ้อนผิดปกติ: โมเดลใหญ่ ให้ตรวจซ้ำบน Server",
            f"ผิวสามเหลี่ยมที่เสีย: {report.degenerate_triangles:,}",
            "คำแนะนำ: กด ‘ซ่อมและตั้งค่าทั้งหมดให้ฉัน’" if report.errors else "ขั้นต่อไป: ตรวจตำแหน่งระเบิดและจุดวัด แล้วสร้างไฟล์สำหรับ Server",
        ]
    )
    return {
        "friendly_summary": friendly,
        "summary": report.readable_summary(),
        "errors": report.errors,
        "warnings": report.warnings,
        "report": asdict(report),
    }


def preview_geometry(path: Path, scale: float, max_triangles: int = 4500) -> Dict[str, Any]:
    """Return an evenly sampled STL mesh small enough for the browser preview."""
    if max_triangles < 1:
        raise ValueError("max_triangles ต้องมากกว่า 0")
    report = STATE.report(path, scale, external=False)
    stride = max(1, math.ceil(report.triangles / max_triangles))
    triangles = []
    for index, triangle in enumerate(iter_stl_triangles(path)):
        if index % stride:
            continue
        triangles.append(
            [round(coordinate * scale, 7) for point in triangle for coordinate in point]
        )
        if len(triangles) >= max_triangles:
            break
    return {
        "triangles": triangles,
        "sampled_triangles": len(triangles),
        "total_triangles": report.triangles,
        "bounds": {
            "minimum": report.bounds.minimum,
            "maximum": report.bounds.maximum,
        },
    }


def automatic_values(report: StlReport, data: Dict[str, Any]) -> Dict[str, Any]:
    domain = auto_domain(
        report.bounds,
        _number(data, "horizontal_buffer"),
        _number(data, "top_buffer"),
    )
    target_cell = _number(data, "target_cell")
    levels = auto_surface_levels(target_cell, report.bounds)
    buffer = _number(data, "horizontal_buffer")
    clearance = max(0.5, min(1.0, domain.span[2] * 0.02))
    return {
        "domain_min": domain.minimum,
        "domain_max": domain.maximum,
        "divisions": mesh_divisions(domain, target_cell),
        "surface_levels": levels,
        "feature_level": levels[0],
        "location": (
            domain.minimum[0] + buffer * 0.25,
            domain.minimum[1] + buffer * 0.25,
            domain.minimum[2] + clearance,
        ),
    }


def request_is_local(host_header: str, origin: str) -> bool:
    """Reject DNS-rebinding and cross-site requests to the localhost adapter."""
    host = host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header
    if host not in {"127.0.0.1", "localhost"}:
        return False
    if origin:
        parsed = urlparse(origin)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            return False
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "BlastUrbanCaseBuilder/1.0"

    def _local_only(self) -> bool:
        if request_is_local(self.headers.get("Host", ""), self.headers.get("Origin", "")):
            return True
        self.send_error(403, "localhost requests only")
        return False

    def log_message(self, format_string: str, *args: Any) -> None:
        print("[web] " + format_string % args)

    def _json(self, status: int, data: Dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_JSON_BYTES:
            raise ValueError("JSON request มีขนาดไม่ถูกต้อง")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("อ่าน JSON request ไม่สำเร็จ") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON request ต้องเป็น object")
        return value

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._local_only():
            return
        path = urlparse(self.path).path
        if path == "/":
            body = HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/defaults":
            default_stl = DEFAULT_TEMPLATE / "constant/triSurface/townBuildings.stl"
            default_output = DEFAULT_WORKSPACE / "cases"
            fetch_output = DEFAULT_WORKSPACE / "results"
            default_output.mkdir(parents=True, exist_ok=True)
            fetch_output.mkdir(parents=True, exist_ok=True)
            exported_cases = local_case_records(default_output)
            latest_case = Path(exported_cases[0]["path"]) if exported_cases else None
            local_images: list[str] = []
            docker = shutil.which("docker")
            if docker:
                try:
                    listed = subprocess.run(
                        [docker, "images", "--format", "{{.Repository}}:{{.Tag}}"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    if listed.returncode == 0:
                        local_images = sorted(
                            {
                                line.strip()
                                for line in listed.stdout.splitlines()
                                if line.strip() and not line.strip().endswith(":<none>")
                            }
                        )
                except (OSError, subprocess.TimeoutExpired):
                    pass
            recommended_image = (
                "local/blastfoam9:web" if "local/blastfoam9:web" in local_images else ""
            )
            self._json(
                200,
                {
                    "stl_path": str(default_stl),
                    "output": str(default_output),
                    "recommended_output": str(default_output),
                    "ssh_key": str(DEFAULT_SSH_KEY),
                    "fetch_output": str(fetch_output),
                    "workspace": str(DEFAULT_WORKSPACE),
                    "latest_case": str(latest_case) if latest_case else "",
                    "local_docker_images": local_images,
                    "recommended_docker_image": recommended_image,
                },
            )
            return
        if path.startswith("/result/"):
            token = path.removeprefix("/result/")
            viewer = STATE.result_viewer(token)
            if viewer is None:
                self.send_error(404)
                return
            body = viewer.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._local_only():
            return
        try:
            path = urlparse(self.path).path
            if path == "/api/upload":
                self._upload()
            elif path == "/api/check":
                self._check()
            elif path == "/api/repair-auto":
                self._repair_auto()
            elif path == "/api/preview":
                self._preview()
            elif path == "/api/source-check":
                self._source_check()
            elif path == "/api/validate":
                self._validate()
            elif path == "/api/export":
                self._export()
            elif path == "/api/local/cases":
                self._local_cases()
            elif path == "/api/local/select-folder":
                self._local_select_folder()
            elif path == "/api/server/install-key":
                self._server_install_key()
            elif path == "/api/server/test-connection":
                self._server_test_connection()
            elif path == "/api/server/check":
                self._server_check()
            elif path == "/api/server/push-image":
                self._server_push_image()
            elif path == "/api/server/prepare-container-image":
                self._server_prepare_container_image()
            elif path == "/api/server/submit":
                self._server_submit()
            elif path == "/api/server/status":
                self._server_status()
            elif path == "/api/server/logs":
                self._server_logs()
            elif path == "/api/server/stop":
                self._server_stop()
            elif path == "/api/server/fetch":
                self._server_fetch()
            elif path == "/api/server/jobs":
                self._server_jobs()
            elif path == "/api/server/delete-job":
                self._server_delete_job()
            elif path == "/api/server/cleanup":
                self._server_cleanup()
            else:
                self.send_error(404)
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})

    def _upload(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            raise ValueError("STL upload ว่างหรือมีขนาดเกิน 8 GiB")
        original = self.headers.get("X-Filename", "model.stl")
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(original).name)
        if not safe.lower().endswith(".stl"):
            raise ValueError("ไฟล์ที่เลือกต้องมีนามสกุล .stl")
        destination = STATE.upload_dir / safe
        counter = 1
        while destination.exists():
            destination = STATE.upload_dir / f"{Path(safe).stem}_{counter}.stl"
            counter += 1
        remaining = length
        with destination.open("wb") as handle:
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("STL upload ขาดหายก่อนครบขนาด")
                handle.write(chunk)
                remaining -= len(chunk)
        self._json(200, {"ok": True, "path": str(destination), "bytes": length})

    def _check(self) -> None:
        data = self._read_json()
        stl = Path(str(data.get("stl_path", "")))
        scale = _number(data, "scale")
        report = STATE.report(stl, scale, external=bool(data.get("external", True)))
        result = {"ok": not report.errors, **report_payload(report)}
        if data.get("auto"):
            result["auto_values"] = automatic_values(report, data)
        self._json(200, result)

    def _repair_auto(self) -> None:
        data = self._read_json()
        source = Path(str(data.get("stl_path", ""))).expanduser().resolve()
        scale = _number(data, "scale")
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem) or "model"
        output = STATE.upload_dir / f"{safe_stem}_repaired.stl"
        counter = 1
        while output.exists():
            output = STATE.upload_dir / f"{safe_stem}_repaired_{counter}.stl"
            counter += 1
        repair = repair_stl(
            source,
            output,
            scale,
            weld_tolerance_m=_number(data, "weld_tolerance"),
            max_hole_size_m=_number(data, "max_hole_size"),
        )

        # Files selected from the browser are already disposable server-side
        # copies.  Replace that copy atomically so every later button uses the
        # repaired geometry at the same active path.  A manually entered path
        # may be the user's real source file, so keep it untouched and switch
        # the UI to the repaired copy instead.
        replaced_active_copy = _is_managed_upload(source)
        if replaced_active_copy:
            output.replace(source)
            active_path = source
            STATE.forget_reports_for(source)
        else:
            active_path = output

        repair.output = str(active_path)
        repair.report_after.path = str(active_path)
        active_path.with_suffix(".repair.json").write_text(
            json.dumps(asdict(repair), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Run the independent OpenFOAM/Docker check on the active repaired file.
        report = STATE.report(active_path, scale, external=True)
        self._json(
            200,
            {
                "ok": not report.errors,
                "path": str(active_path),
                "active_name": active_path.name,
                "replaced_active_copy": replaced_active_copy,
                "repair_summary": repair.readable_summary(),
                "repair": {
                    "welded_vertices": repair.welded_vertices,
                    "removed_degenerate": repair.removed_degenerate,
                    "removed_duplicate_faces": repair.removed_duplicate_faces,
                    "boundary_loops_found": repair.boundary_loops_found,
                    "holes_filled": repair.holes_filled,
                    "holes_skipped_too_large": repair.holes_skipped_too_large,
                    "holes_skipped_not_planar": repair.holes_skipped_not_planar,
                    "holes_skipped_complex": repair.holes_skipped_complex,
                    "triangles_added": repair.triangles_added,
                },
                **report_payload(report),
                "auto_values": automatic_values(report, data),
            },
        )

    def _preview(self) -> None:
        data = self._read_json()
        path = Path(str(data.get("stl_path", ""))).expanduser().resolve()
        scale = _number(data, "scale")
        self._json(200, {"ok": True, **preview_geometry(path, scale)})

    def _source_check(self) -> None:
        data = self._read_json()
        config = payload_to_config(data)
        stl = Path(config.stl_path).expanduser().resolve()
        report = STATE.report(stl, config.stl_scale, external=False)
        inside, distance = point_surface_relation(stl, config.stl_scale, config.charge_centre)
        radius = config.theoretical_charge_radius
        if not config.domain.contains(config.charge_centre, margin=radius):
            level = "error"
            message = "Source หรือตัวทรงกลมอยู่นอก Domain"
        elif inside:
            level = "error"
            message = "Source อยู่ภายในผิวอาคาร กรุณาย้ายตำแหน่ง"
        elif distance < radius:
            level = "error"
            message = f"Source ตัดผิวอาคาร: ห่าง {distance:.4g} m แต่รัศมี {radius:.4g} m"
        elif report.errors:
            level = "warning"
            message = "ตำแหน่งไม่ตัดผิวที่พบ แต่โมเดลยังมีรอยเปิด จึงควรซ่อมก่อนยืนยัน"
        else:
            level = "ok"
            message = f"ตำแหน่ง Source ใช้ได้ · ระยะจากผิวอาคารใกล้สุด {distance:.4g} m"
        self._json(
            200,
            {
                "ok": level == "ok",
                "level": level,
                "message": message,
                "inside_model": inside,
                "distance_to_surface": distance,
                "radius": radius,
            },
        )

    def _validate(self) -> None:
        data = self._read_json()
        config = payload_to_config(data)
        report = STATE.report(Path(config.stl_path), config.stl_scale, external=False)
        errors, warnings = validate_config(config, report, inspect_points=True)
        self._json(
            200,
            {
                "ok": not errors,
                "errors": errors,
                "warnings": warnings,
                "estimate": config.estimate(),
                "charge_radius": config.theoretical_charge_radius,
                "actual_cell_size": config.actual_cell_size,
                "base_cells": config.base_cells,
            },
        )

    def _export(self) -> None:
        data = self._read_json()
        config = payload_to_config(data)
        output_text = str(data.get("output", "")).strip()
        if not output_text:
            raise ValueError("กรุณาระบุ Output folder")
        output = Path(output_text).expanduser()
        report = STATE.report(Path(config.stl_path), config.stl_scale, external=False)
        target, archive, warnings = create_case(
            config,
            output,
            report,
            create_archive=bool(data.get("archive", True)),
        )
        self._json(
            200,
            {
                "ok": True,
                "target": str(target),
                "archive": str(archive) if archive else "",
                "warnings": warnings,
            },
        )

    def _local_cases(self) -> None:
        data = self._read_json()
        output_text = str(data.get("output", "")).strip()
        parent = Path(output_text).expanduser().resolve() if output_text else DEFAULT_WORKSPACE / "cases"
        self._json(
            200,
            {
                "ok": True,
                "parent": str(parent),
                "cases": local_case_records(parent),
            },
        )

    def _local_select_folder(self) -> None:
        """Open the trusted host's native folder chooser for this localhost UI."""
        data = self._read_json()
        purpose = str(data.get("purpose", "")).strip()
        if purpose not in {"output", "case"}:
            raise ValueError("ประเภทการเลือกโฟลเดอร์ไม่ถูกต้อง")

        suggested_text = str(data.get("suggested", "")).strip()
        suggested = Path(suggested_text).expanduser().resolve() if suggested_text else DEFAULT_WORKSPACE
        if not suggested.is_dir():
            suggested = suggested.parent
        if not suggested.is_dir():
            suggested = DEFAULT_WORKSPACE
        suggested.mkdir(parents=True, exist_ok=True)

        osascript = shutil.which("osascript")
        if not osascript:
            raise ValueError("เครื่องนี้ไม่มี native folder picker; กรุณาใช้งาน Web UI บน macOS")
        prompt = "เลือกโฟลเดอร์หลักสำหรับบันทึกหลาย Case" if purpose == "output" else "เลือกโฟลเดอร์ Case ที่จะส่งไป Server"
        process = subprocess.run(
            [
                osascript,
                "-e", "on run argv",
                "-e", "set startFolder to POSIX file (item 1 of argv) as alias",
                "-e", "set pickedFolder to choose folder with prompt (item 2 of argv) default location startFolder",
                "-e", "return POSIX path of pickedFolder",
                "-e", "end run",
                str(suggested),
                prompt,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
        if process.returncode:
            if "User canceled" in process.stderr or "(-128)" in process.stderr:
                self._json(200, {"ok": True, "cancelled": True})
                return
            raise ValueError("เปิดหน้าต่างเลือกโฟลเดอร์ไม่สำเร็จ: " + process.stderr.strip())
        selected = Path(process.stdout.strip()).expanduser().resolve()
        if not selected.is_dir():
            raise ValueError("โฟลเดอร์ที่เลือกไม่มีอยู่")
        if purpose == "case":
            missing = missing_case_files(selected)
            if missing:
                raise ValueError("โฟลเดอร์ที่เลือกไม่ใช่ Case ที่สร้างจาก BlastUrban ครบถ้วน · ขาด: " + ", ".join(missing))
        self._json(200, {"ok": True, "cancelled": False, "path": str(selected)})

    def _server_install_key(self) -> None:
        data = self._read_json()
        host, user, port, key = _server_connection(data)
        key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not key.is_file():
            generated = subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "BlastUrban Web UI", "-f", str(key)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
            if generated.returncode:
                raise ValueError("สร้าง SSH key ไม่สำเร็จ: " + generated.stderr.strip())
        key.chmod(0o600)
        command = [
            "ssh-copy-id",
            "-i",
            str(key.with_suffix(key.suffix + ".pub")),
            "-p",
            str(port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{user}@{host}",
        ]
        _run_password_pty(command, str(data.get("server_password", "")))
        self._json(200, {"ok": True, "key": str(key), "message": "ติดตั้ง SSH key แล้ว; password ไม่ได้ถูกบันทึก"})

    def _server_test_connection(self) -> None:
        """Test SSH independently, before involving Docker or the solver image."""
        data = self._read_json()
        connection = _server_connection(data)
        process = _run_remote(
            connection,
            r'''
set -eu
python3 - <<'PY'
import json, os, platform, pwd, socket

memory_kib = 0
try:
    with open("/proc/meminfo", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("MemTotal:"):
                memory_kib = int(line.split()[1])
                break
except OSError:
    pass

print(json.dumps({
    "host": socket.gethostname(),
    "user": pwd.getpwuid(os.getuid()).pw_name,
    "home": os.path.expanduser("~"),
    "architecture": platform.machine(),
    "cpu_threads": os.cpu_count() or 0,
    "memory_gib": round(memory_kib / 1048576, 1),
}))
PY
''',
            timeout=30,
        )
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("เชื่อม SSH ได้ แต่อ่านข้อมูล Server ไม่สำเร็จ") from exc
        self._json(200, {"ok": True, **result})

    def _server_check(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        requested_root = _remote_root(data)
        selected_image = str(data.get("docker_image", "")).strip()
        if selected_image and not re.fullmatch(r"[A-Za-z0-9_./:@+-]+", selected_image):
            raise ValueError("ชื่อ Docker image ไม่ถูกต้อง")
        script = r'''
set -eu
selected=${1:-}
requested_root=$2
python3 - "$selected" "$requested_root" "$3" "${4:-}" <<'PY'
import json, os, platform, shutil, socket, subprocess, sys

def run(command):
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except OSError as exc:
        return 127, "", str(exc)

def number(command, default=0):
    code, output, _ = run(command)
    try:
        return int(output)
    except (TypeError, ValueError):
        return default

memory_kib = 0
try:
    with open("/proc/meminfo", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("MemTotal:"):
                memory_kib = int(line.split()[1])
                break
except OSError:
    pass
disk = shutil.disk_usage(os.getcwd())
docker_code, docker_version, docker_error = run(["docker", "version", "--format", "{{.Server.Version}}"])
images = []
containers = []
container_checks = {}
if docker_code == 0:
    _, image_text, _ = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    images = sorted({line for line in image_text.splitlines() if line and not line.endswith(":<none>")})
    _, container_text, _ = run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Image}}|{{.Status}}"])
    containers = [line for line in container_text.splitlines() if line]
    container_command = sys.argv[3]
    for record in containers:
        name, _, status = (record.split("|", 2) + ["", ""])[:3]
        if status.startswith("Up"):
            code, output, error = run(["docker", "exec", "--user", "0", name, "/bin/bash", "-c", container_command])
            container_checks[name] = {"ok": code == 0, "needs_vtk": code == 3, "detail": (output + "\n" + error).strip()[-1000:]}
systemd_code, _, systemd_error = run(["systemctl", "--user", "show-environment"])
selected = sys.argv[1]
requested_root = os.path.abspath(sys.argv[2])
recommended_root = os.path.join(os.path.expanduser("~"), "BlastUrbanJobs")
root_ok = False
root_error = ""
try:
    os.makedirs(requested_root, exist_ok=True)
    root_ok = os.path.isdir(requested_root) and os.access(requested_root, os.W_OK | os.X_OK)
    if not root_ok:
        root_error = "ไม่มีสิทธิ์เขียนโฟลเดอร์นี้"
except OSError as exc:
    root_error = str(exc)
image_check = None
if selected and docker_code == 0:
    platform_args = ["--platform", sys.argv[4]] if sys.argv[4] else []
    _, image_platform, _ = run(["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", selected])
    code, output, error = run(
        ["docker", "run", "--rm", *platform_args, "--entrypoint", "/bin/bash", selected, "-c", container_command]
    )
    detail = (output + "\n" + error).strip()[-1000:]
    if code == 3 and not detail:
        detail = "ไม่พบ Python VTK"
    image_check = {
        "ok": code == 0,
        "needs_vtk": code == 3,
        "cannot_execute": code == 4,
        "exit_code": code,
        "platform": image_platform,
        "detail": detail,
    }
print(json.dumps({
    "host": socket.gethostname(),
    "architecture": platform.machine(),
    "cpu_threads": os.cpu_count() or 0,
    "memory_gib": round(memory_kib / 1048576, 1),
    "disk_free_gib": round(disk.free / 1073741824, 1),
    "docker_ok": docker_code == 0,
    "docker_version": docker_version,
    "docker_error": docker_error[-1000:],
    "images": images,
    "containers": containers,
    "container_checks": container_checks,
    "systemd_user_ok": systemd_code == 0,
    "systemd_error": systemd_error[-1000:],
    "image_check": image_check,
    "remote_root": requested_root,
    "remote_root_ok": root_ok,
    "remote_root_error": root_error,
    "recommended_root": recommended_root,
}))
PY
'''
        platform_name = str(data.get("docker_platform", "")).strip()
        if platform_name not in {"", "linux/amd64", "linux/arm64"}:
            raise ValueError("Docker platform ไม่ถูกต้อง")
        process = _run_remote(
            connection, script, (selected_image, str(requested_root), IMAGE_READY_CHECK, platform_name), timeout=180
        )
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("อ่านข้อมูล Server ไม่สำเร็จ: " + process.stdout[-2000:]) from exc
        self._json(200, {"ok": True, **result})

    def _server_push_image(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        image = str(data.get("docker_image", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_./:@+-]+", image):
            raise ValueError("กรุณาระบุชื่อ Docker image บน Mac")
        inspected = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        if inspected.returncode:
            raise ValueError(f"ไม่พบ Docker image บน Mac: {image}")
        ssh_command = _ssh_args(*connection) + ["gzip -dc | docker load"]
        save = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert save.stdout is not None
        compressor = subprocess.Popen(["gzip", "-1"], stdin=save.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        save.stdout.close()
        assert compressor.stdout is not None
        remote = subprocess.Popen(
            ssh_command,
            stdin=compressor.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        compressor.stdout.close()
        try:
            remote_stdout, remote_stderr = remote.communicate(timeout=3600)
        except subprocess.TimeoutExpired:
            remote.kill()
            save.kill()
            compressor.kill()
            raise ValueError("ส่ง Docker image ใช้เวลานานเกิน 1 ชั่วโมง")
        save_stderr = save.stderr.read() if save.stderr else b""
        compressor_stderr = compressor.stderr.read() if compressor.stderr else b""
        save_code = save.wait(timeout=30)
        compressor_code = compressor.wait(timeout=30)
        if save_code or compressor_code or remote.returncode:
            detail = (remote_stderr + compressor_stderr + save_stderr).decode("utf-8", errors="replace")
            raise ValueError("ส่ง Docker image ไม่สำเร็จ: " + detail[-2000:])
        self._json(
            200,
            {
                "ok": True,
                "image": image,
                "message": "ส่ง Docker image ไป Server และ docker load สำเร็จ",
                "detail": remote_stdout.decode("utf-8", errors="replace").strip(),
            },
        )

    def _server_prepare_container_image(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        container = str(data.get("server_container", "")).strip()
        image = str(data.get("ready_docker_image", "")).strip()
        safe_pattern = r"[A-Za-z0-9_./:@+-]+"
        if not re.fullmatch(safe_pattern, container):
            raise ValueError("กรุณาเลือก Docker container ที่กำลังรัน")
        if not re.fullmatch(safe_pattern, image):
            raise ValueError("ชื่อ image ใหม่ไม่ถูกต้อง")
        script = r'''
set -eu
container=$1
image=$2
running=$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)
[[ $running == true ]] || { printf 'Container ไม่ได้กำลังรัน: %s\n' "$container" >&2; exit 1; }

docker exec --user 0 "$container" /bin/bash -c '
    set -eu
    vtk_ok=0
    for python in /usr/bin/python3 python3; do
        if command -v "$python" >/dev/null 2>&1 && "$python" -c "import vtk" >/dev/null 2>&1; then
            vtk_ok=1
            break
        fi
    done
    if [[ $vtk_ok != 1 ]]; then
        command -v apt-get >/dev/null 2>&1 || { echo "Container ไม่มี apt-get สำหรับติดตั้ง VTK" >&2; exit 2; }
        export DEBIAN_FRONTEND=noninteractive
        apt-get -qq -o=Dpkg::Use-Pty=0 update
        package=""
        for candidate in python3-vtk9 python3-vtk7 python3-vtk; do
            if apt-cache show "$candidate" >/dev/null 2>&1; then package=$candidate; break; fi
        done
        [[ -n $package ]] || { echo "ไม่พบ package Python VTK ใน apt repository" >&2; exit 2; }
        apt-get -qq -o=Dpkg::Use-Pty=0 install -y "$package"
    fi
    /usr/bin/python3 -c "import vtk; print(vtk.VTK_VERSION)"
'

image_id=$(docker commit "$container" "$image")
docker run --rm --user 0:0 --entrypoint /bin/bash "$image" -c "$3"
printf 'READY_IMAGE=%s\nIMAGE_ID=%s\n' "$image" "$image_id"
'''
        process = _run_remote(connection, script, (container, image, IMAGE_READY_CHECK), timeout=1800)
        self._json(
            200,
            {
                "ok": True,
                "container": container,
                "image": image,
                "message": "ติดตั้ง VTK และสร้าง image พร้อมคำนวณแล้ว",
                "detail": process.stdout.strip()[-3000:],
            },
        )

    @staticmethod
    def _server_case(data: Dict[str, Any]) -> Tuple[PurePosixPath, str, PurePosixPath]:
        root = _remote_root(data)
        case_name = safe_case_name(str(data.get("server_case_name", "")))
        return root, case_name, root / case_name

    def _server_submit(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        root, case_name, remote_case = self._server_case(data)
        local_text = str(data.get("local_case_path", "")).strip()
        if not local_text:
            raise ValueError("กรุณาเลือก Case จาก Mac ก่อนส่ง")
        local_case = Path(local_text).expanduser().resolve()
        missing = missing_case_files(local_case)
        if missing:
            raise ValueError("Local case ไม่ครบ กรุณา Export เคสใหม่จาก Web UI ก่อน · ขาด: " + ", ".join(missing))
        exclude_file = PROJECT_ROOT / "tools/remote-rsync-excludes.txt"
        if not exclude_file.is_file():
            raise ValueError(f"ไม่พบไฟล์ตั้งค่า rsync: {exclude_file}")
        image = str(data.get("docker_image", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_./:@+-]+", image):
            raise ValueError("กรุณาเลือก Docker image")
        cores_cap = _integer(data, "server_cores")
        memory = _integer(data, "server_memory")
        core_mode = str(data.get("server_core_mode", "auto")).strip()
        if core_mode not in {"auto", "manual"}:
            raise ValueError("โหมดเลือก CPU ไม่ถูกต้อง")
        if not 1 <= cores_cap <= 512 or not 2 <= memory <= 4096:
            raise ValueError("จำนวน Core หรือ RAM limit ไม่ถูกต้อง")
        platform_name = str(data.get("docker_platform", "")).strip()
        if platform_name not in {"", "linux/amd64", "linux/arm64"}:
            raise ValueError("Docker platform ไม่ถูกต้อง")

        try:
            _run_remote(
                connection,
                r'''
set -eu
docker image inspect "$1" >/dev/null
platform_args=()
[[ -z $2 ]] || platform_args=(--platform "$2")
docker run --rm ${platform_args[@]+"${platform_args[@]}"} --user 0:0 --entrypoint /bin/bash "$1" -c "$3"
''',
                (image, platform_name, IMAGE_READY_CHECK),
                timeout=240,
            )
        except ValueError as exc:
            raise ValueError(
                "Docker image ยังไม่พร้อมสำหรับ blastFoam/Web 3D; "
                "กด ‘เตรียม Image จาก Container นี้ + ติดตั้ง VTK’ ก่อน\n" + str(exc)
            ) from exc

        cores = cores_cap
        if core_mode == "auto":
            selected = _run_remote(
                connection,
                r'''
set -eu
cap=$1
total=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc)
load=$(awk '{n=int($1); if ($1>n) n++; print n}' /proc/loadavg)
if (( total > 2 )); then reserve=2; else reserve=1; fi
usable=$((total - reserve))
(( usable >= 1 )) || usable=1
idle=$((total - load - reserve))
(( idle >= 1 )) || idle=1
selected=$idle
(( selected > usable )) && selected=$usable
(( selected > cap )) && selected=$cap
printf '%s\n' "$selected"
''',
                (str(cores_cap),),
            )
            try:
                cores = int(selected.stdout.strip())
            except ValueError as exc:
                raise ValueError("Server เลือกจำนวน CPU อัตโนมัติไม่สำเร็จ") from exc

        allocation = _run_remote(
            connection,
            r'''
set -eu
requested_root=$1
name=$2
root=$requested_root
if ! mkdir -p -- "$root" 2>/dev/null || [[ ! -w $root || ! -x $root ]]; then
    root="$HOME/BlastUrbanJobs"
    mkdir -p -- "$root" || {
        printf 'ไม่มีสิทธิ์สร้างทั้ง %s และ %s\n' "$requested_root" "$root" >&2
        exit 1
    }
fi
candidate="$root/$name"
suffix=$(date +%Y%m%d-%H%M%S)
counter=0
while ! mkdir -- "$candidate" 2>/dev/null; do
    if [[ ! -e $candidate ]]; then
        printf 'สร้างโฟลเดอร์ Case ไม่สำเร็จ: %s\n' "$candidate" >&2
        exit 1
    fi
    counter=$((counter + 1))
    candidate="$root/${name}-${suffix}"
    if (( counter > 1 )); then
        candidate="$root/${name}-${suffix}-${counter}"
    fi
done
printf '%s\n%s\n' "$root" "$candidate"
''',
            (str(root), case_name),
        )
        allocated_lines = [line.strip() for line in allocation.stdout.splitlines() if line.strip()]
        if len(allocated_lines) != 2:
            raise ValueError("Server ส่งตำแหน่ง Case กลับมาไม่ครบ")
        actual_root = PurePosixPath(allocated_lines[0])
        remote_case = PurePosixPath(allocated_lines[1])
        if (
            not str(actual_root).startswith("/")
            or ".." in actual_root.parts
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(actual_root))
            or remote_case.parent != actual_root
        ):
            raise ValueError("Server ส่งตำแหน่ง Case ที่ไม่ถูกต้องกลับมา")
        actual_case_name = safe_case_name(remote_case.name)
        host, user, port, key = connection
        ssh_shell = shlex.join(
            ["ssh", "-i", str(key), "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
        )
        transfer = subprocess.run(
            [
                "rsync", "-az", "--partial", "--human-readable", "--exclude-from", str(exclude_file),
                "-e", ssh_shell, str(local_case) + "/", f"{user}@{host}:{remote_case}/",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1800,
            check=False,
        )
        if transfer.returncode:
            raise ValueError(
                f"ส่ง case ด้วย rsync ไม่สำเร็จ (โฟลเดอร์บน Server ที่สร้างไว้และยังไม่ได้เริ่มงาน: {remote_case}): "
                + transfer.stderr[-2000:]
            )
        submit_script = r'''
set -eu
case_dir=$1 image=$2 cores=$3 memory=$4 platform=$5
shift 5
cd -- "$case_dir"
missing=""
for required in "$@"; do
    [[ -f $required ]] || missing="$missing $required"
done
compgen -G "constant/triSurface/*.stl" >/dev/null || missing="$missing constant/triSurface/*.stl"
compgen -G "0/*.orig" >/dev/null || missing="$missing 0/*.orig"
if [[ -n $missing ]]; then
    printf 'rsync ส่งไฟล์ไม่ครบ ขาด:%s\n' "$missing" >&2
    exit 1
fi
chmod +x server-docker-job.sh makeWebResults.sh preflight.sh Allrun organizeSurfaceCheckOutput.sh
./server-docker-job.sh submit "$image" "$cores" "$memory" "$platform"
'''
        process = _run_remote(
            connection,
            submit_script,
            (str(remote_case), image, str(cores), str(memory), platform_name, *REQUIRED_CASE_FILES),
            timeout=120,
        )
        self._json(
            200,
            {
                "ok": True,
                "case_name": actual_case_name,
                "remote_root": str(actual_root),
                "remote_case": str(remote_case),
                "unit": process.stdout.strip().splitlines()[-1],
                "cores": cores,
                "core_mode": core_mode,
                "message": (
                    "ส่งเคสและเริ่มงานผ่าน systemd/Docker แล้ว"
                    if actual_root == root
                    else f"โฟลเดอร์เดิมไม่มีสิทธิ์เขียน จึงย้ายงานอัตโนมัติไป {actual_root}"
                ),
            },
        )

    def _server_status(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        _, _, remote_case = self._server_case(data)
        process = _run_remote(
            connection,
            r'''
set -eu
case_dir=$1
if [[ -f $case_dir/server-docker-job.sh ]]; then
    cd -- "$case_dir"
    bash ./server-docker-job.sh status
elif [[ -f $case_dir/server-job-status.json ]]; then
    cat -- "$case_dir/server-job-status.json"
else
    state=not_submitted
    message='โฟลเดอร์งานยังว่างหรือส่งไฟล์ไม่ครบ กรุณากดส่งงานใหม่ หรือเลือกงานที่ส่งสำเร็จจากหน้าผลลัพธ์'
    [[ -d $case_dir ]] || {
        state=not_found
        message='ไม่พบโฟลเดอร์งานนี้บน Server กรุณาเลือกงานจากหน้าผลลัพธ์ หรือส่งงานใหม่'
    }
    python3 - "$state" "$message" "$case_dir" <<'PY'
import datetime
import json
import socket
import sys

print(json.dumps({
    "state": sys.argv[1],
    "message": sys.argv[2],
    "case": sys.argv[3],
    "host": socket.gethostname(),
    "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, ensure_ascii=False))
PY
fi
''',
            (str(remote_case),),
        )
        try:
            status = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("อ่านสถานะงานไม่สำเร็จ") from exc
        self._json(200, {"ok": True, "status": status})

    def _server_logs(self) -> None:
        """Return a bounded diagnostic tail without downloading the whole case."""
        data = self._read_json()
        connection = _server_connection(data)
        _, _, remote_case = self._server_case(data)
        process = _run_remote(
            connection,
            r'''
set -eu
case_dir=$1
[[ -d $case_dir ]] || { printf 'ไม่พบโฟลเดอร์งาน: %s\n' "$case_dir" >&2; exit 1; }
python3 - "$case_dir" <<'PY'
import os
import pathlib
import re
import subprocess
import sys

case_dir = pathlib.Path(sys.argv[1])
parts = [f"CASE: {case_dir}"]
status = case_dir / "server-job-status.json"
if status.is_file():
    parts.extend(["\n===== STATUS =====", status.read_text(encoding="utf-8", errors="replace")[-12000:]])

unit_file = case_dir / "server-job-unit.txt"
if unit_file.is_file():
    unit = unit_file.read_text(encoding="utf-8", errors="replace").strip()
    if re.fullmatch(r"[A-Za-z0-9_.@:-]+", unit):
        journal = subprocess.run(
            ["journalctl", "--user", "-u", unit, "--no-pager", "-n", "350", "-o", "cat"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        parts.extend([f"\n===== SYSTEMD JOURNAL: {unit} =====", journal.stdout[-90000:]])

logs = []
for root, directories, files in os.walk(case_dir):
    root_path = pathlib.Path(root)
    depth = len(root_path.relative_to(case_dir).parts)
    if depth >= 2:
        directories[:] = []
    for name in files:
        if not (name.startswith("log.") or name.endswith(".log")):
            continue
        path = root_path / name
        try:
            logs.append((path.stat().st_mtime, path, path.relative_to(case_dir)))
        except OSError:
            continue
for _, path, relative in sorted(logs, reverse=True)[:16]:
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 24000))
            tail = stream.read().decode("utf-8", errors="replace")
        parts.extend([f"\n===== {relative} (ท้ายไฟล์) =====", tail])
    except OSError as exc:
        parts.append(f"\nอ่าน {relative} ไม่สำเร็จ: {exc}")

print("\n".join(parts)[-180000:])
PY
''',
            (str(remote_case),),
            timeout=90,
        )
        self._json(200, {"ok": True, "case": str(remote_case), "logs": process.stdout})

    def _server_stop(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        _, _, remote_case = self._server_case(data)
        _run_remote(connection, 'cd "$1"\n./server-docker-job.sh stop', (str(remote_case),), timeout=60)
        self._json(200, {"ok": True, "message": "ส่งคำสั่งหยุดงานแล้ว"})

    def _server_fetch(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        _, case_name, remote_case = self._server_case(data)
        host, user, port, key = connection
        local_parent = Path(
            str(data.get("fetch_output", DEFAULT_WORKSPACE / "results"))
        ).expanduser().resolve()
        gate = _run_remote(
            connection,
            r'''
set -eu
cd -- "$1" 2>/dev/null || { echo not_found; exit 0; }
if [[ -f server-docker-job.sh ]]; then
    bash ./server-docker-job.sh status | python3 -c "import sys,json;print(json.load(sys.stdin).get('state',''))"
else
    echo legacy
fi
''',
            (str(remote_case),),
        ).stdout.strip().splitlines()[-1:]
        remote_state = gate[0] if gate else ""
        if remote_state in {"queued", "running", "postprocessing"}:
            raise ValueError(f"งานยังทำงานอยู่ (สถานะ {remote_state}) จึงยังดึงผลไม่ได้")
        if remote_state in {"failed", "viewer_failed", "stopped", "not_submitted", "not_found"}:
            raise ValueError(f"ไม่ดึงผลจากงานสถานะ {remote_state}; อ่าน Log เพื่อดูสาเหตุ")
        destination = local_parent / case_name
        destination.mkdir(parents=True, exist_ok=True)
        # Mirror (delete stale files) only inside a folder this tool created,
        # never inside a user-chosen folder that may hold other data.
        marker = destination / ".blasturban-results"
        mirror_flags = ["--delete", "--exclude", marker.name] if marker.is_file() else []
        ssh_shell = shlex.join(
            ["ssh", "-i", str(key), "-p", str(port), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
        )
        transfer = subprocess.run(
            ["rsync", "-az", "--partial", *mirror_flags, "--human-readable", "-e", ssh_shell,
             f"{user}@{host}:{remote_case}/results-web/", str(destination) + "/"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1800,
            check=False,
        )
        if transfer.returncode:
            raise ValueError("ดึงผล Web ไม่สำเร็จ: " + transfer.stderr[-2000:])
        marker.write_text("managed by BlastUrban fetch; stale files are mirrored away\n", encoding="utf-8")
        viewer = destination / "blast3D.html"
        viewer_url = ""
        if viewer.is_file():
            token = STATE.register_result_viewer(viewer)
            viewer_url = f"/result/{token}"
        self._json(
            200,
            {
                "ok": True,
                "destination": str(destination),
                "viewer": str(viewer),
                "viewer_url": viewer_url,
            },
        )

    def _server_jobs(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        root = _remote_root(data)
        script = r'''
set -eu
python3 - "$1" <<'PY'
import datetime
import json
import os
import shutil
import subprocess
import sys

root = os.path.realpath(sys.argv[1])
jobs = []
if os.path.isdir(root):
    for entry in os.scandir(root):
        if not entry.is_dir(follow_symlinks=False):
            continue
        status = {}
        status_path = os.path.join(entry.path, "server-job-status.json")
        try:
            with open(status_path, encoding="utf-8") as stream:
                status = json.load(stream)
        except (OSError, ValueError, TypeError):
            pass
        size_kib = 0
        measured = subprocess.run(
            ["du", "-sk", "--", entry.path], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if measured.returncode == 0:
            try:
                size_kib = int(measured.stdout.split()[0])
            except (ValueError, IndexError):
                pass
        modified = entry.stat(follow_symlinks=False).st_mtime
        state = str(status.get("state", "ยังไม่เริ่ม"))
        message = str(status.get("message", ""))
        active = state in {"queued", "running", "postprocessing"}
        if active:
            # Never trust the status file alone: confirm the systemd unit lives.
            try:
                with open(os.path.join(entry.path, "server-job-unit.txt"), encoding="utf-8") as stream:
                    unit = stream.read().strip()
            except OSError:
                unit = ""
            if unit and all(c.isalnum() or c in "_.@:-" for c in unit):
                try:
                    unit_alive = subprocess.run(
                        ["systemctl", "--user", "is-active", "--quiet", unit], check=False
                    ).returncode == 0
                except OSError:
                    unit_alive = True  # cannot verify; keep the reported state
                if not unit_alive:
                    state, active = "failed", False
                    message = f"systemd unit {unit} ไม่ทำงานแล้วแต่สถานะยังเป็น {status.get('state')}; กด ‘ดูสถานะ’ เพื่อบันทึกสถานะที่ถูกต้อง"
        jobs.append({
            "name": entry.name,
            "state": state,
            "message": message,
            "updated": str(status.get("updated_utc", datetime.datetime.fromtimestamp(
                modified, datetime.timezone.utc).isoformat())),
            "size_bytes": size_kib * 1024,
            "has_web_result": os.path.isfile(os.path.join(entry.path, "results-web", "blast3D.html")),
            "active": active,
        })
jobs.sort(key=lambda item: item["updated"], reverse=True)
usage = shutil.disk_usage(root if os.path.isdir(root) else os.path.dirname(root) or "/")
print(json.dumps({
    "jobs": jobs,
    "disk_free_bytes": usage.free,
    "disk_total_bytes": usage.total,
}, ensure_ascii=False))
PY
'''
        process = _run_remote(connection, script, (str(root),), timeout=180)
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("อ่านรายการงานบน Server ไม่สำเร็จ") from exc
        self._json(200, {"ok": True, **result})

    def _server_delete_job(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        root = _remote_root(data)
        requested = str(data.get("cleanup_case_name", "")).strip()
        case_name = safe_case_name(requested)
        if requested != case_name:
            raise ValueError("ชื่องานที่เลือกไม่ถูกต้อง")
        script = r'''
set -eu
python3 - "$1" "$2" <<'PY'
import json
import os
import shutil
import subprocess
import sys

root = os.path.realpath(sys.argv[1])
name = sys.argv[2]
target = os.path.realpath(os.path.join(root, name))
if os.path.dirname(target) != root or os.path.basename(target) != name:
    raise SystemExit("refusing path outside the configured job folder")
if not os.path.isdir(target) or os.path.islink(os.path.join(root, name)):
    raise SystemExit("job folder not found or is not a regular directory")
state = ""
try:
    with open(os.path.join(target, "server-job-status.json"), encoding="utf-8") as stream:
        state = str(json.load(stream).get("state", ""))
except (OSError, ValueError, TypeError):
    pass
unit_active = False
try:
    with open(os.path.join(target, "server-job-unit.txt"), encoding="utf-8") as stream:
        unit = stream.read().strip()
    if unit and all(c.isalnum() or c in "_.@:-" for c in unit):
        unit_active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit], check=False
        ).returncode == 0
except OSError:
    pass
if state in {"queued", "running", "postprocessing"} or unit_active:
    raise SystemExit("งานยังทำงานอยู่ กรุณาหยุดงานและรอให้หยุดก่อนลบ")
shutil.rmtree(target)
print(json.dumps({"deleted": name, "state": state}, ensure_ascii=False))
PY
'''
        process = _run_remote(connection, script, (str(root), case_name), timeout=180)
        result = json.loads(process.stdout)
        self._json(200, {"ok": True, **result})

    def _server_cleanup(self) -> None:
        data = self._read_json()
        connection = _server_connection(data)
        root = _remote_root(data)
        try:
            days = int(data.get("cleanup_days", 30))
        except (TypeError, ValueError) as exc:
            raise ValueError("จำนวนวันต้องเป็นตัวเลขจำนวนเต็ม") from exc
        if not 1 <= days <= 36500:
            raise ValueError("จำนวนวันต้องอยู่ระหว่าง 1–36500")
        script = r'''
set -eu
python3 - "$1" "$2" <<'PY'
import json
import os
import shutil
import sys
import time

root = os.path.realpath(sys.argv[1])
days = int(sys.argv[2])
cutoff = time.time() - days * 86400
terminal = {"complete", "failed", "viewer_failed", "stopped"}
deleted = []
kept = []
if os.path.isdir(root):
    for entry in os.scandir(root):
        if not entry.is_dir(follow_symlinks=False):
            continue
        status = {}
        try:
            with open(os.path.join(entry.path, "server-job-status.json"), encoding="utf-8") as stream:
                status = json.load(stream)
        except (OSError, ValueError, TypeError):
            pass
        state = str(status.get("state", ""))
        if state in terminal and entry.stat(follow_symlinks=False).st_mtime < cutoff:
            shutil.rmtree(entry.path)
            deleted.append(entry.name)
        else:
            kept.append(entry.name)
print(json.dumps({"deleted": deleted, "kept_count": len(kept), "days": days}, ensure_ascii=False))
PY
'''
        process = _run_remote(connection, script, (str(root), str(days)), timeout=600)
        result = json.loads(process.stdout)
        self._json(200, {"ok": True, **result})


def main() -> None:
    configured_port = os.environ.get("BLAST_CASE_UI_PORT")
    port = int(configured_port or DEFAULT_PORT)
    try:
        server = ThreadingHTTPServer((HOST, port), Handler)
    except OSError:
        if configured_port:
            raise
        server = ThreadingHTTPServer((HOST, 0), Handler)
    actual_port = server.server_address[1]
    url = f"http://{HOST}:{actual_port}/"
    print(f"BlastUrban Browser UI: {url}")
    print("กด Control-C ใน Terminal เพื่อปิดโปรแกรม")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping BlastUrban Browser UI")
    finally:
        server.server_close()
        STATE.close()


if __name__ == "__main__":
    main()
