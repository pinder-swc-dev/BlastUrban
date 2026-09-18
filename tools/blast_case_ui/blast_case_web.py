#!/usr/bin/env python3
"""Dependency-free localhost web UI for the BlastUrban case builder.

This front end avoids the system Tk 8.5 framework shipped with Apple's
Command Line Tools, which cannot create windows on some macOS 26 releases.
The HTTP server binds to 127.0.0.1 only and never exposes itself to the LAN.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
    mesh_divisions,
    parse_probes,
    repair_stl,
    validate_config,
)


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
HTML_PATH = Path(__file__).with_name("web") / "index.html"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024


class AppState:
    def __init__(self) -> None:
        # Keep temporary uploads inside the repository so Docker Desktop can
        # mount them on macOS.  /var/folders and /private/tmp are not shared by
        # every Docker Desktop/Colima configuration.
        runtime_parent = DEFAULT_TEMPLATE / "generatedCases"
        runtime_parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(tempfile.mkdtemp(prefix=".ui-work-", dir=runtime_parent))
        self.reports: Dict[Tuple[str, float], StlReport] = {}
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


STATE = AppState()


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


class Handler(BaseHTTPRequestHandler):
    server_version = "BlastUrbanCaseBuilder/1.0"

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
            default_output = DEFAULT_TEMPLATE / "generatedCases"
            self._json(200, {"stl_path": str(default_stl), "output": str(default_output)})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            path = urlparse(self.path).path
            if path == "/api/upload":
                self._upload()
            elif path == "/api/check":
                self._check()
            elif path == "/api/repair-auto":
                self._repair_auto()
            elif path == "/api/validate":
                self._validate()
            elif path == "/api/export":
                self._export()
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
        report = STATE.report(stl, scale, external=True)
        result = {"ok": not report.errors, **report_payload(report)}
        if data.get("auto"):
            result["auto_values"] = automatic_values(report, data)
        self._json(200, result)

    def _repair_auto(self) -> None:
        data = self._read_json()
        source = Path(str(data.get("stl_path", "")))
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
        output.with_suffix(".repair.json").write_text(
            json.dumps(asdict(repair), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Run the independent OpenFOAM/Docker check on the repaired copy too.
        report = STATE.report(output, scale, external=True)
        self._json(
            200,
            {
                "ok": not report.errors,
                "path": str(output),
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
