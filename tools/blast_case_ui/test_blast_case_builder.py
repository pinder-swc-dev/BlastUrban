#!/usr/bin/env python3
"""Regression tests for the dependency-free case builder."""

from __future__ import annotations

import tempfile
import struct
import unittest
from pathlib import Path

from blast_case_builder import (
    DEFAULT_TEMPLATE,
    CaseConfig,
    analyse_stl,
    auto_domain,
    create_case,
    parse_probes,
    repair_stl,
    validate_config,
)


TETRA_STL = """solid tetra
facet normal 0 0 -1
 outer loop
  vertex 0 0 0
  vertex 0 1 0
  vertex 1 0 0
 endloop
endfacet
facet normal 0 -1 0
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 0 1
 endloop
endfacet
facet normal -1 0 0
 outer loop
  vertex 0 0 0
  vertex 0 0 1
  vertex 0 1 0
 endloop
endfacet
facet normal 1 1 1
 outer loop
  vertex 1 0 0
  vertex 0 1 0
  vertex 0 0 1
 endloop
endfacet
endsolid tetra
"""

OPEN_TETRA_STL = TETRA_STL.replace("""facet normal 1 1 1
 outer loop
  vertex 1 0 0
  vertex 0 1 0
  vertex 0 0 1
 endloop
endfacet
""", "")


class StlTests(unittest.TestCase):
    def test_ascii_closed_surface_and_scale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tetra.stl"
            path.write_text(TETRA_STL, encoding="ascii")
            report = analyse_stl(path, scale=2.0, run_external=False)
        self.assertEqual(report.encoding, "ASCII")
        self.assertEqual(report.triangles, 4)
        self.assertEqual(report.open_edges, 0)
        self.assertEqual(report.non_manifold_edges, 0)
        self.assertEqual(report.bounds.maximum, (2.0, 2.0, 2.0))
        self.assertAlmostEqual(report.surface_area, (0.5 * 3 + 3 ** 0.5 / 2) * 4)

    def test_binary_stl_with_trailing_exporter_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binary-with-footer.stl"
            header = b"solid binary model".ljust(80, b"\0")
            triangle = struct.pack(
                "<12fH",
                0, 0, 1,
                0, 0, 0,
                1, 0, 0,
                0, 1, 0,
                0,
            )
            path.write_bytes(header + struct.pack("<I", 1) + triangle + b"CAD-METADATA")
            report = analyse_stl(path, run_external=False)
        self.assertEqual(report.encoding, "binary")
        self.assertEqual(report.triangles, 1)
        self.assertEqual(report.bounds.maximum, (1.0, 1.0, 0.0))

    def test_rejects_non_finite_stl_coordinates(self) -> None:
        invalid = TETRA_STL.replace("vertex 0 0 0", "vertex nan 0 0", 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nan.stl"
            path.write_text(invalid, encoding="ascii")
            with self.assertRaisesRegex(ValueError, "NaN"):
                analyse_stl(path, run_external=False)

    def test_auto_domain_has_ground_and_buffers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tetra.stl"
            path.write_text(TETRA_STL, encoding="ascii")
            report = analyse_stl(path, run_external=False)
        domain = auto_domain(report.bounds, 5, 8)
        self.assertEqual(domain.minimum, (-5.0, -5.0, 0.0))
        self.assertEqual(domain.maximum, (6.0, 6.0, 9.0))

    def test_probe_parser(self) -> None:
        self.assertEqual(parse_probes("1 2 3 # one\n(4, 5, 6)\n"), [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])

    def test_repairs_a_small_planar_hole_without_overwriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "open.stl"
            output = Path(directory) / "open_repaired.stl"
            source.write_text(OPEN_TETRA_STL, encoding="ascii")
            original = source.read_bytes()
            result = repair_stl(source, output, scale=1, weld_tolerance_m=0.0001, max_hole_size_m=2)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(result.report_before.open_edges, 3)
            self.assertEqual(result.holes_filled, 1)
            self.assertEqual(result.triangles_added, 1)
            self.assertEqual(result.report_after.open_edges, 0)
            self.assertEqual(result.report_after.non_manifold_edges, 0)

    def test_does_not_guess_how_to_fill_a_hole_above_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "open.stl"
            output = Path(directory) / "open_repaired.stl"
            source.write_text(OPEN_TETRA_STL, encoding="ascii")
            result = repair_stl(source, output, scale=1, weld_tolerance_m=0, max_hole_size_m=0.5)
            self.assertEqual(result.holes_filled, 0)
            self.assertEqual(result.holes_skipped_too_large, 1)
            self.assertEqual(result.report_after.open_edges, 3)


class CaseGenerationTests(unittest.TestCase):
    def test_rejects_charge_that_cannot_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stl = Path(directory) / "tetra.stl"
            stl.write_text(TETRA_STL, encoding="ascii")
            report = analyse_stl(stl, run_external=False)
            config = CaseConfig(
                stl_path=str(stl),
                domain_min=(-5, -5, 0),
                domain_max=(8, 8, 8),
                divisions=(13, 13, 8),
                location_in_mesh=(-3, -3, 1),
                charge_centre=(3, 3, 1),
                charge_mass=0.1,
                charge_refinement_level=2,
                probes=[(4, 3, 1)],
            )
            errors, _ = validate_config(config, report)
            self.assertTrue(any("Charge refinement" in message for message in errors))

    def test_generates_complete_non_overwriting_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stl = root / "small model.stl"
            stl.write_text(TETRA_STL, encoding="ascii")
            stl.with_suffix(".repair.json").write_text('{"holes_filled": 1}\n', encoding="utf-8")
            report = analyse_stl(stl, run_external=False)
            config = CaseConfig(
                case_name="testCase3D",
                stl_path=str(stl),
                domain_min=(-5, -5, 0),
                domain_max=(8, 8, 8),
                divisions=(13, 13, 8),
                location_in_mesh=(-3, -3, 1),
                charge_centre=(3, 3, 1),
                charge_refinement_level=7,
                plane_point=(3, 3, 1),
                probes=[(4, 3, 1)],
                snappy_max_cells=100_000,
                dynamic_max_cells=200_000,
                mpi_ranks=10,
            )
            errors, _ = validate_config(config, report, inspect_points=True)
            self.assertEqual(errors, [])
            target, archive, _ = create_case(config, root / "out", report, DEFAULT_TEMPLATE, True)
            self.assertTrue(archive and archive.is_file())
            self.assertTrue((target / "0/p").is_file())
            self.assertTrue((target / "geometry-repair.json").is_file())
            self.assertTrue((target / "organizeSurfaceCheckOutput.sh").stat().st_mode & 0o111)
            self.assertIn("organizeSurfaceCheck", (target / "Allrun").read_text())
            self.assertTrue((target / "preflight.sh").stat().st_mode & 0o111)
            self.assertTrue((target / "server-run-auto.sh").stat().st_mode & 0o111)
            self.assertTrue((target / "server-docker-job.sh").stat().st_mode & 0o111)
            self.assertTrue((target / "makeWebResults.sh").stat().st_mode & 0o111)
            docker_job = (target / "server-docker-job.sh").read_text()
            self.assertIn("set +e", docker_job)
            self.assertIn("/root/OpenFOAM/blastfoam/etc/bashrc", docker_job)
            self.assertIn("--user 0:0", docker_job)
            self.assertIn("BLAST_HOST_UID", docker_job)
            self.assertNotIn("--package-only", docker_job)
            self.assertIn("BLAST_CASE_NAME", (target / "makeWebResults.sh").read_text())
            preflight = (target / "preflight.sh").read_text()
            self.assertIn("blastToVTK", preflight)
            self.assertIn("calculateImpulse", preflight)
            self.assertNotIn("paraFoam", preflight)
            self.assertTrue((target / "visualization/exportBlast3D.py").is_file())
            self.assertTrue((target / "visualization/viewer_template.html").is_file())
            self.assertIn("BLAST_MAX_CORES=10", (target / "server-job.env").read_text())
            self.assertIn("numberOfSubdomains 10", (target / "system/decomposeParDict").read_text())
            self.assertIn('file "small_model.stl"', (target / "system/snappyHexMeshDict").read_text())
            self.assertIn("centre (3 3 1)", (target / "system/setFieldsDict").read_text())
            with self.assertRaises(FileExistsError):
                create_case(config, root / "out", report, DEFAULT_TEMPLATE, False)

    def test_viewer_does_not_hard_code_the_iso_pressure(self) -> None:
        viewer = (DEFAULT_TEMPLATE / "visualization/viewer_template.html").read_text(encoding="utf-8")
        self.assertNotIn("110 kPa", viewer)
        self.assertIn("waveIsoKPa", viewer)


if __name__ == "__main__":
    unittest.main()
