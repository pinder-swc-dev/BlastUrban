#!/usr/bin/env python3
"""Small regression tests for Browser UI data helpers."""

from __future__ import annotations

import os
import json
import hashlib
import inspect
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from blast_case_web import (
    AppState,
    HTML_PATH,
    Handler,
    IMAGE_READY_CHECK,
    PROJECT_ROOT,
    STATE,
    SSH_MULTIPLEX_ENABLED,
    TRUSTED_RUNTIME_ASSETS,
    _charge_sources,
    _ssh_transport_args,
    local_case_records,
    missing_case_files,
    preview_geometry,
    request_is_local,
    stage_trusted_runtime_assets,
    validate_fetch_state,
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

    def test_source_placement_uses_stl_coordinates_and_model_relative_height(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertRegex(html, r'id="charge_x"[^>]*placeholder="เลือกบนโมเดลหรือกรอกค่า"')
        self.assertRegex(html, r'id="charge_y"[^>]*placeholder="เลือกบนโมเดลหรือกรอกค่า"')
        self.assertRegex(html, r'id="charge_height"[^>]*value="1"')
        self.assertRegex(html, r'id="charge_z"[^>]*type="hidden"')
        self.assertIn("function beginSourcePlacement()", html)
        self.assertIn('id="preview_source_position"', html)
        self.assertIn('id="preview_source_status"', html)
        self.assertIn("function sourceXYFromPointer(event)", html)
        self.assertIn("preview.hoverSource=sourceXYFromPointer(event)", html)
        self.assertIn("preview.bounds.minimum[2]", html)
        self.assertIn("modelBaseZ()+height", html)
        self.assertIn("syncSourceDependents()", html)
        self.assertNotRegex(html, r'id="charge_[xy]"[^>]*value=')

    def test_ui_collects_multiple_sources_with_mass_position_and_delay(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertIn('id="source_select"', html)
        self.assertIn('id="source_delay"', html)
        self.assertIn('class="grid source-grid"', html)
        self.assertIn('class="verify" type="button" onclick="checkSourcePosition()"', html)
        self.assertIn("function addSource()", html)
        self.assertIn("function removeActiveSource()", html)
        self.assertIn("data.sources=blastSources.map", html)
        self.assertIn("blastSources.forEach((source,index)=>", html)
        sources = _charge_sources(
            {
                "sources": [
                    {"centre": [1, 2, 3], "mass": 4, "delay": 0},
                    {"centre": [5, 6, 7], "mass": 8, "delay": 0.002},
                ]
            }
        )
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[1].centre, (5.0, 6.0, 7.0))
        self.assertEqual(sources[1].mass, 8.0)
        self.assertEqual(sources[1].delay, 0.002)

    def test_ui_exposes_only_supported_blastfoam_numerical_features(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        for element_id in ("flux_scheme", "time_integrator", "spatial_order"):
            self.assertIn(f'id="{element_id}"', html)
            self.assertRegex(html, rf"const ids = \[[\s\S]*'{element_id}'")
        for runtime_type in ("Tadmor", "Kurganov", "HLLC", "AUSM+", "RK1SSP", "RK4SSP"):
            self.assertIn(f'value="{runtime_type}"', html)
        self.assertIn("quadratic MUSCL/Minmod", html)

    def test_model_preview_uses_the_available_desktop_height(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertIn("display:flex; flex-direction:column", html)
        self.assertIn(".preview-layout { display:grid; flex:1; height:auto; min-height:330px", html)
        self.assertNotIn("height:min(48vh,520px)", html)

    def test_balanced_fast_profile_keeps_viewer_quality_with_fewer_outputs(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertRegex(html, r'id="performance_profile"[^>]*>')
        self.assertIn("Balanced Fast — ดูแนวคลื่นเร็ว", html)
        self.assertIn("benchmark จริงพบค่า peak ที่ probes ต่าง 11–26%", html)
        self.assertIn("maxDelta:2e-6,frames:48", html)
        self.assertIn("cell:2,snappy:3000000,dynamic:3000000", html)

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

    def test_trusted_runtime_overlay_is_current_and_never_contains_cfd_inputs(self) -> None:
        relative_names = {relative for relative, _ in TRUSTED_RUNTIME_ASSETS}
        self.assertIn("server-docker-job.sh", relative_names)
        self.assertIn("visualization/exportBlast3D.py", relative_names)
        self.assertIn("visualization/viewer_template.html", relative_names)
        self.assertNotIn("Allrun", relative_names)
        self.assertNotIn("preflight.sh", relative_names)
        self.assertFalse(any(name.startswith(("system/", "constant/", "0/")) for name in relative_names))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            hashes = stage_trusted_runtime_assets(destination)
            manifest = json.loads(
                (destination / "blasturban-runtime-assets.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["assets"], hashes)
            for relative_name, source in TRUSTED_RUNTIME_ASSETS:
                staged = destination / relative_name
                self.assertEqual(staged.read_bytes(), source.read_bytes())
                self.assertEqual(hashes[relative_name], hashlib.sha256(source.read_bytes()).hexdigest())

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
IN_CONTAINER_INSTALLER = Path(__file__).with_name("install-inside-ubuntu2204.sh")


class RunnerContractTests(unittest.TestCase):
    def test_runner_reports_solver_progress_and_eta_from_real_log_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            runner = case / "server-docker-job.sh"
            shutil.copy2(ASSETS / "server-docker-job.sh", runner)
            (case / "system").mkdir()
            (case / "system/controlDict").write_text("endTime 0.01;\n", encoding="utf-8")
            (case / "log.blastFoam").write_text(
                "Time = 0.005\nExecutionTime = 20 s  ClockTime = 20 s\n",
                encoding="utf-8",
            )
            started = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
            (case / "server-job-status.json").write_text(
                json.dumps(
                    {
                        "state": "running",
                        "message": "Docker is meshing or calculating blastFoam",
                        "created_utc": started,
                        "state_started_utc": started,
                        "updated_utc": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                ["bash", str(runner), "status"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            status = json.loads(process.stdout)
        self.assertEqual(status["progress"]["stage"], "solving")
        self.assertAlmostEqual(status["progress"]["fraction"], 0.5)
        self.assertAlmostEqual(status["progress"]["eta_seconds"], 20.0)
        self.assertGreaterEqual(status["progress"]["elapsed_seconds"], 29)

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

    def test_in_container_installer_has_no_docker_dependency(self) -> None:
        installer = IN_CONTAINER_INSTALLER.read_text(encoding="utf-8")
        self.assertIn("Ubuntu 22.04", installer)
        self.assertIn("openfoam9", installer)
        self.assertIn("python3-vtk9", installer)
        self.assertIn("./Allwmake", installer)
        self.assertIn("blastFoam -help", installer)
        self.assertNotRegex(installer, r"(?m)^\s*docker(?:\s|$)")

    def test_image_readiness_avoids_login_shell_and_runs_solver(self) -> None:
        self.assertNotIn("-lc", IMAGE_READY_CHECK)
        self.assertIn("blastFoam -help", IMAGE_READY_CHECK)
        self.assertIn('[ ! -x "$blast_path" ]', IMAGE_READY_CHECK)
        self.assertNotIn("$USER", IMAGE_READY_CHECK)
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

    def test_fetch_rejects_every_non_success_state(self) -> None:
        for state in ("running", "failed", "stopped", "not_found"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                validate_fetch_state(state)
        validate_fetch_state("complete")
        validate_fetch_state("legacy")

    def test_linger_helper_can_be_driven_by_fake_loginctl(self) -> None:
        runner = ASSETS / "server-docker-job.sh"
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "loginctl"
            fake.write_text("#!/bin/sh\nprintf 'no\\n'\n", encoding="utf-8")
            fake.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = directory + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                [str(runner), "check-linger"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "no")

    def test_runner_refuses_submit_without_linger_or_explicit_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "case"
            (case / "system").mkdir(parents=True)
            (case / "system/decomposeParDict").write_text(
                "numberOfSubdomains 1;\n", encoding="utf-8"
            )
            runner = case / "server-docker-job.sh"
            shutil.copy2(ASSETS / "server-docker-job.sh", runner)
            runner.chmod(0o755)
            fake_bin = Path(directory) / "bin"
            fake_bin.mkdir()
            for name, body in {
                "loginctl": "printf 'no\\n'",
                "docker": "exit 0",
                "systemctl": "exit 0",
                "systemd-run": "exit 99",
            }.items():
                command = fake_bin / name
                command.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
                command.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                [str(runner), "submit", "fixture:image", "1", "2", "", "false"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=10,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("submission refused", result.stderr)
        self.assertIn("sudo loginctl enable-linger", result.stderr)
        self.assertNotIn("systemd-run could not start", result.stderr)

    def test_resource_names_are_bounded_deduplicated_and_collision_resistant(self) -> None:
        runner = ASSETS / "server-docker-job.sh"
        prefix = "blasturban-" + "same-prefix-" * 8
        names = []
        for original in (prefix + "alpha", prefix + "beta"):
            result = subprocess.run(
                [str(runner), "resource-name", original, "20261002112233-99999"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            names.append(result.stdout.strip())
        self.assertTrue(all(len(name) <= 63 for name in names))
        self.assertTrue(all(not name.startswith("blasturban-blasturban-") for name in names))
        self.assertNotEqual(names[0], names[1])

    def test_runner_status_contract_includes_linger_and_docker_outcome(self) -> None:
        runner = (ASSETS / "server-docker-job.sh").read_text(encoding="utf-8")
        for field in ("accept_no_linger", "docker_exit_code", "oom_killed"):
            self.assertIn(f'"{field}"', runner)
        self.assertIn("sudo loginctl enable-linger", runner)
        self.assertIn('--cpus "$viewer_cpus"', runner)

    def test_verified_postprocess_recovery_preserves_original_unit_failure(self) -> None:
        source = (ASSETS / "server-docker-job.sh").read_text(encoding="utf-8")
        self.assertIn("def valid_postprocess_recovery", source)
        self.assertIn('"postprocess_reused_identical_vtk_export"', source)
        self.assertIn('recovery.get("postprocess_exit_code") == 0', source)
        self.assertIn('recovery.get("viewer_verified") is True', source)
        self.assertIn('recovery.get("archive_sha256_verified") is True', source)
        self.assertIn("and not postprocess_recovered", source)

    def test_status_accepts_newer_verified_viewer_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "blasturban-viewer-recovery"
            (case / "results-web").mkdir(parents=True)
            runner = case / "server-docker-job.sh"
            shutil.copy2(ASSETS / "server-docker-job.sh", runner)
            runner.chmod(0o755)
            viewer = case / "results-web/blast3D.html"
            viewer.write_text("verified viewer", encoding="utf-8")
            archive = case / "result.tar.gz"
            archive.write_bytes(b"verified archive")
            recorded = datetime.now(timezone.utc) - timedelta(minutes=2)
            recovered = recorded + timedelta(minutes=1)
            status = {
                "state": "complete",
                "updated_utc": recovered.isoformat(),
                "completed_utc": recovered.isoformat(),
                "recovery": {
                    "method": "postprocess_only_adaptive_voxel_export",
                    "cfd_rerun": False,
                    "postprocess_exit_code": 0,
                    "viewer_verified": True,
                    "archive_sha256_verified": True,
                    "archive_name": archive.name,
                    "viewer_html_bytes": viewer.stat().st_size,
                    "recovered_utc": recovered.isoformat(),
                },
            }
            (case / "server-job-status.json").write_text(json.dumps(status), encoding="utf-8")
            (case / "server-job-unit-result.json").write_text(
                json.dumps({
                    "service_result": "exit-code",
                    "exit_status": "1",
                    "recorded_utc": recorded.isoformat(),
                }),
                encoding="utf-8",
            )
            (case / "server-job-unit.txt").write_text("blasturban-recovered-unit\n", encoding="utf-8")
            fake_bin = case / "fake-bin"
            fake_bin.mkdir()
            systemctl = fake_bin / "systemctl"
            systemctl.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' 'LoadState=not-found' 'ActiveState=inactive' "
                "'SubState=dead' 'Result=success' 'ExecMainStatus=0'\n",
                encoding="utf-8",
            )
            systemctl.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            result = subprocess.run(
                [str(runner), "status"], cwd=case, env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["state"], "complete")
            self.assertEqual(
                json.loads((case / "server-job-status.json").read_text(encoding="utf-8"))["state"],
                "complete",
            )

    def test_web_package_keeps_only_a_bounded_solver_log_tail(self) -> None:
        script = (ASSETS / "makeWebResults.sh").read_text(encoding="utf-8")
        self.assertIn("tail -c 2097152 log.blastFoam", script)
        self.assertIn("log.blastFoam.tail", script)
        self.assertNotIn("for file in log.blastFoam ", script)

    def test_runner_records_fake_oom_without_running_cfd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / "blasturban-oom-fixture"
            (case / "system").mkdir(parents=True)
            (case / "system/decomposeParDict").write_text(
                "numberOfSubdomains 1;\n", encoding="utf-8"
            )
            runner = case / "server-docker-job.sh"
            shutil.copy2(ASSETS / "server-docker-job.sh", runner)
            runner.chmod(0o755)
            fake_bin = Path(directory) / "bin"
            fake_bin.mkdir()
            docker = fake_bin / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                "case $1 in\n"
                "  run) exit 137 ;;\n"
                "  inspect) printf 'true\\n' ;;\n"
                "  rm) exit 0 ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                [str(runner), "execute", "fixture:image", "1", "2", "", "no", "true"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=20,
                check=False,
            )
            status = json.loads((case / "server-job-status.json").read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 137)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["failure"], "out_of_memory")
        self.assertEqual(status["docker_exit_code"], 137)
        self.assertIs(status["oom_killed"], True)
        self.assertEqual(status["linger"], "no")
        self.assertIs(status["accept_no_linger"], True)

    def test_rsync_payload_excludes_large_source_only_trees(self) -> None:
        excludes = (PROJECT_ROOT / "tools/remote-rsync-excludes.txt").read_text(encoding="utf-8")
        self.assertIn("/media/", excludes)
        self.assertIn("/validation/", excludes)
        self.assertIn("**/__pycache__/", excludes)

    def test_bulk_cleanup_endpoint_is_dry_run_only(self) -> None:
        source = inspect.getsource(Handler._server_cleanup)
        self.assertIn('"dry_run": True', source)
        self.assertNotIn("shutil.rmtree", source)
        html = HTML_PATH.read_text(encoding="utf-8")
        self.assertIn("เคลียร์งานค้าง (dry-run)", html)

    def test_delete_job_keeps_path_unit_and_audit_safeguards(self) -> None:
        source = inspect.getsource(Handler._server_delete_job)
        self.assertIn("os.path.realpath", source)
        self.assertIn("os.path.islink", source)
        self.assertIn('"systemctl", "--user", "is-active"', source)
        self.assertIn('"--network=none"', source)
        self.assertIn('"--pull=never"', source)
        self.assertIn('audit("permissions_repaired")', source)
        self.assertLess(source.index("permissions_repaired"), source.index("shutil.rmtree"))
        self.assertIn('audit("deleted")', source)

    def test_submit_rejects_duplicate_active_case_before_allocating_suffix(self) -> None:
        source = inspect.getsource(Handler._server_submit)
        guard = source.index("ปฏิเสธการส่งซ้ำ")
        suffix = source.index("suffix=$(date")
        self.assertLess(guard, suffix)

    def test_submit_reports_measured_rsync_time_and_bytes(self) -> None:
        source = inspect.getsource(Handler._server_submit)
        self.assertIn('"--stats"', source)
        self.assertIn('"transfer_seconds"', source)
        self.assertIn('"transferred_bytes"', source)
        self.assertIn('"transfer_mib_s"', source)
        self.assertIn("systemctl --user is-active --quiet", source)
        self.assertIn('"--checksum"', source)
        self.assertIn('"runtime_assets_refreshed"', source)
        self.assertIn("trusted runtime asset checksum mismatch", source)

    def test_ssh_transport_reuses_one_short_protected_control_path(self) -> None:
        if not SSH_MULTIPLEX_ENABLED:
            self.skipTest("BLASTURBAN_SSH_MULTIPLEX=0")
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "id_ed25519"
            key.write_text("test-only-placeholder", encoding="utf-8")
            key.chmod(0o600)
            first = _ssh_transport_args("192.0.2.10", "blastuser", 22, key)
            second = _ssh_transport_args("192.0.2.10", "blastuser", 22, key)
        control = next(value for value in first if value.startswith("ControlPath="))
        self.assertEqual(control, next(value for value in second if value.startswith("ControlPath=")))
        self.assertLess(len(os.fsencode(control.removeprefix("ControlPath="))), 100)
        self.assertEqual(STATE.ssh_control_dir.stat().st_mode & 0o777, 0o700)
        self.assertIn("ControlMaster=auto", first)
        self.assertIn("ControlPersist=60", first)

    def test_shutdown_survives_second_ctrl_c_and_kills_stuck_ssh_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "blast_case_web.DEFAULT_WORKSPACE", Path(directory)
        ):
            state = AppState()
            upload_dir = state.upload_dir
            socket_path = state.ssh_control_dir / "cm-shutdown-test"
            socket_path.touch()
            state.ssh_masters[("192.0.2.10", "tester", 22, "/tmp/test-key")] = socket_path
            process = mock.Mock()
            process.wait.side_effect = [KeyboardInterrupt(), None]
            process.poll.return_value = None
            with mock.patch("blast_case_web.subprocess.Popen", return_value=process):
                state.close()
            process.kill.assert_called_once_with()
            self.assertFalse(socket_path.exists())
            self.assertFalse(upload_dir.exists())
            # A repeated server_close() must remain a harmless no-op.
            state.close()

    def test_image_cache_is_keyed_by_image_id_and_reversible(self) -> None:
        source = (Path(__file__).with_name("blast_case_web.py")).read_text(encoding="utf-8")
        self.assertIn('BLASTURBAN_IMAGE_READY_CACHE", "1"', source)
        self.assertIn('docker", "image", "inspect", "--format", "{{.Id}}"', source)
        self.assertIn('f"{image_id}|{sys.argv[4]}|v1"', source)


if __name__ == "__main__":
    unittest.main()
