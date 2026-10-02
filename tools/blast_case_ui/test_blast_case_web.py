#!/usr/bin/env python3
"""Small regression tests for Browser UI data helpers."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from blast_case_web import (
    HTML_PATH,
    IMAGE_READY_CHECK,
    PROJECT_ROOT,
    STATE,
    local_case_records,
    missing_case_files,
    preview_geometry,
    request_is_local,
)
from test_blast_case_builder import TETRA_STL


class PreviewTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        STATE.close()

    def test_preview_is_scaled_and_limited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tetra.stl"
            path.write_text(TETRA_STL, encoding="ascii")
            result = preview_geometry(path, scale=2.0, max_triangles=2)
        self.assertEqual(result["total_triangles"], 4)
        self.assertEqual(result["sampled_triangles"], 2)
        self.assertEqual(result["bounds"]["maximum"], (2.0, 2.0, 2.0))
        self.assertTrue(all(len(triangle) == 9 for triangle in result["triangles"]))

    def test_web_page_ids_and_buttons_are_wired(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        element_ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(element_ids), len(set(element_ids)), "HTML contains duplicate IDs")
        referenced_ids = set(re.findall(r"\bel\('([^']+)'\)", html))
        self.assertEqual(referenced_ids - set(element_ids), set(), "JavaScript references missing elements")
        handlers = set(re.findall(r'onclick="([A-Za-z_$][\w$]*)\(', html))
        functions = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", html))
        self.assertEqual(handlers - functions, set(), "Buttons reference missing functions")

    def test_result_viewer_registration_only_accepts_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            viewer = Path(directory) / "blast3D.html"
            viewer.write_text("<!doctype html><title>result</title>", encoding="utf-8")
            token = STATE.register_result_viewer(viewer)
            self.assertEqual(STATE.result_viewer(token), viewer.resolve())
            wrong_type = Path(directory) / "result.txt"
            wrong_type.write_text("not a viewer", encoding="utf-8")
            with self.assertRaises(ValueError):
                STATE.register_result_viewer(wrong_type)

    def test_rsync_exclude_file_is_resolved_from_project_root(self) -> None:
        self.assertTrue((PROJECT_ROOT / "tools/remote-rsync-excludes.txt").is_file())

    def test_local_case_library_only_lists_complete_generated_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            older = parent / "case-a"
            newer = parent / "case-b"
            incomplete = parent / "not-a-case"
            for candidate in (older, newer, incomplete):
                candidate.mkdir()
                (candidate / "case-builder.json").write_text(
                    '{"config":{"case_name":"' + candidate.name + '","charge_mass":10}}',
                    encoding="utf-8",
                )
            for candidate in (older, newer):
                (candidate / "server-docker-job.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            os.utime(older / "case-builder.json", (100, 100))
            os.utime(newer / "case-builder.json", (200, 200))
            records = local_case_records(parent)
        self.assertEqual([record["name"] for record in records], ["case-b", "case-a"])
        self.assertEqual(records[0]["charge_mass"], 10)

    def test_case_paths_require_explicit_ui_selection(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertRegex(html, r'id="output"[^>]*readonly')
        self.assertRegex(html, r'id="local_case_path"[^>]*readonly')
        self.assertIn("chooseOutputFolder()", html)
        self.assertIn("chooseLocalCaseFolder()", html)
        self.assertIn("localCaseConfirmed", html)


ASSETS = Path(__file__).with_name("assets")
WORKER_DOCKERFILE = Path(__file__).with_name("Dockerfile.ubuntu2204-worker")
WORKER_ENTRYPOINT = ASSETS / "blasturban-container-entrypoint.sh"
WORKER_BUILD_SCRIPT = Path(__file__).with_name("build-ubuntu2204-worker.sh")


class RunnerContractTests(unittest.TestCase):
    def test_ubuntu2204_worker_build_contract(self) -> None:
        dockerfile = WORKER_DOCKERFILE.read_text(encoding="utf-8")
        entrypoint = WORKER_ENTRYPOINT.read_text(encoding="utf-8")
        build_script = WORKER_BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("FROM ubuntu:22.04", dockerfile)
        self.assertIn("openfoam9", dockerfile)
        self.assertIn("python3-vtk9", dockerfile)
        self.assertIn("./Allwmake", dockerfile)
        self.assertNotIn("EXPOSE", dockerfile)
        self.assertIn("/opt/openfoam9/etc/bashrc", entrypoint)
        self.assertIn("/opt/blastfoam/etc/bashrc", entrypoint)
        self.assertIn("blastFoam -help", build_script)
        self.assertIn("import vtk", build_script)

    def test_image_readiness_avoids_login_shell_and_runs_solver(self) -> None:
        self.assertNotIn("-lc", IMAGE_READY_CHECK)
        self.assertIn("blastFoam -help", IMAGE_READY_CHECK)
        source = (Path(__file__).with_name("blast_case_web.py")).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"/bin/bash\"?,? *\"?-lc|bash -lc '")
        runner = (ASSETS / "server-docker-job.sh").read_text(encoding="utf-8")
        self.assertNotIn("-lc", runner)

    def test_exit_trap_does_not_reference_function_locals(self) -> None:
        runner = (ASSETS / "server-docker-job.sh").read_text(encoding="utf-8")
        self.assertIn("trap finish_execute EXIT", runner)
        self.assertNotIn("trap cleanup EXIT", runner)
        self.assertIn("record-unit-result", runner)
        self.assertIn("ExecStopPost", runner)

    def test_root_container_may_run_mpi(self) -> None:
        runner = (ASSETS / "server-docker-job.sh").read_text(encoding="utf-8")
        self.assertIn("OMPI_ALLOW_RUN_AS_ROOT=1", runner)

    def test_localhost_guard_rejects_foreign_host_and_origin(self) -> None:
        self.assertTrue(request_is_local("127.0.0.1:8765", ""))
        self.assertTrue(request_is_local("localhost:8765", "http://127.0.0.1:8765"))
        self.assertFalse(request_is_local("evil.example:8765", ""))
        self.assertFalse(request_is_local("127.0.0.1:8765", "https://evil.example"))

    def test_incomplete_case_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            (case / "case-builder.json").write_text("{}", encoding="utf-8")
            missing = missing_case_files(case)
        self.assertIn("server-docker-job.sh", missing)
        self.assertIn("constant/triSurface/*.stl", missing)
        self.assertNotIn("case-builder.json", missing)

    def test_slurm_runner_never_leaves_an_active_state_behind(self) -> None:
        script = (ASSETS / "server-run-auto.sh").read_text(encoding="utf-8")
        self.assertIn("trap finish_execute EXIT", script)
        self.assertNotIn("trap cleanup EXIT", script)
        # A refused duplicate run must not overwrite the running job's status.
        self.assertLess(script.index("flock -n 9"), script.index("trap finish_execute EXIT"))
        self.assertIn("sbatch could not submit", script)
        self.assertNotIn('write_status complete', script)

    def test_narrow_server_tab_keeps_action_buttons_reachable(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        media = re.search(r"@media \(max-width:1180px\)\s*\{(.*?)\}\s*\n", html, re.S)
        self.assertIsNotNone(media)
        self.assertRegex(html, r"#tab-server \.card:last-child>\.buttons\{position:sticky;bottom:0")


if __name__ == "__main__":
    unittest.main()
