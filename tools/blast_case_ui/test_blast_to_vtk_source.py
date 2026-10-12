import ast
import math
import re
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BLAST_TO_VTK = PROJECT_ROOT / "applications/utilities/blastToVTK/blastToVTK.C"
EXPORTER = PROJECT_ROOT / "tutorials/blastFoam/building3DWorkshop/visualization/exportBlast3D.py"
VIEWER = PROJECT_ROOT / "tutorials/blastFoam/building3DWorkshop/visualization/viewer_template.html"


class BlastToVTKSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = BLAST_TO_VTK.read_text(encoding="utf-8")

    def test_only_mpi_master_opens_shared_vtk_output(self) -> None:
        self.assertNotIn("std::ofstream os(file, std::ios::binary)", self.source)
        self.assertIn("if (Pstream::master())", self.source)
        self.assertIn("os.open(file, std::ios::binary)", self.source)

    def test_single_sample_option_preserves_full_time_table(self) -> None:
        self.assertIn('"sampleTime"', self.source)
        self.assertIn('args.optionRead<scalar>("sampleTime")', self.source)
        self.assertIn("sampleTimes.setSize(1)", self.source)


class CompactVisualizationSourceTests(unittest.TestCase):
    @staticmethod
    def _exporter_function(name):
        tree = ast.parse(EXPORTER.read_text(encoding="utf-8"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        namespace = {"math": math, "re": re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(EXPORTER), "exec"), namespace)
        return namespace[name]

    def test_surface_voxels_are_bounded_and_reference_real_faces(self) -> None:
        voxelize = self._exporter_function("surface_voxels")
        mesh = {
            "points": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            "faces": [[0, 1, 2], [0, 2, 3]],
        }
        result = voxelize(mesh, 0.1, 40)
        self.assertLessEqual(len(result["cells"]), 40)
        self.assertGreater(len(result["cells"]), 0)
        self.assertGreaterEqual(result["size"], 0.1)
        self.assertTrue(all(cell[3] in (0, 1) for cell in result["cells"]))

    def test_large_pressure_plane_adapts_instead_of_failing_frame(self) -> None:
        grid = self._exporter_function("bounded_plane_grid")
        width, height, spacing = grid(199.4, 200.0, 0.1, 500_000)
        self.assertLessEqual(width * height, 500_000)
        self.assertGreater(spacing, 0.1)
        self.assertLess(spacing, 0.4)

    def test_case_stl_path_uses_generated_snappy_filename(self) -> None:
        resolve = self._exporter_function("case_stl_path")
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary)
            (case / "system").mkdir()
            (case / "constant/triSurface").mkdir(parents=True)
            expected = case / "constant/triSurface/user-model.stl"
            expected.write_text("solid smoke\nendsolid smoke\n", encoding="utf-8")
            (case / "system/snappyHexMeshDict").write_text(
                'geometry { walls { type triSurfaceMesh; file "user-model.stl"; } }',
                encoding="utf-8",
            )
            self.assertEqual(resolve(case), expected)

    def test_exporter_uses_real_pressure_slices_and_shared_wall_geometry(self) -> None:
        source = EXPORTER.read_text(encoding="utf-8")
        self.assertIn("postProcessing/pressureSlices/overpressure_", source)
        self.assertIn('"wallGeometry": wall_geometry', source)
        self.assertIn('default=48', source)
        self.assertIn('default=0.1', source)
        self.assertIn("def voxel_plane", source)
        self.assertIn("def wave_overpressure", source)
        self.assertIn('wave["op"] = wave_overpressure', source)
        self.assertIn('"ambientPressureKPa"', source)
        self.assertIn("def blast_sources(case):", source)
        self.assertIn('"blastCenters": charge_centres', source)
        self.assertIn('"blastSources": sources', source)
        self.assertIn("def surface_voxels", source)
        self.assertIn("def case_stl_path", source)
        self.assertIn("stl_geometry(case_stl_path(case))", source)
        self.assertNotIn('case / "constant/triSurface/townBuildings.stl"', source)
        self.assertIn('"modelVoxels": model_voxels', source)
        self.assertIn('"waveVoxels": wave_voxels', source)
        self.assertIn("def bounded_plane_grid", source)
        self.assertIn("max_pixels=500_000", source)
        self.assertIn("skipped_layers.append", source)
        self.assertIn('"requestedCellSize": requested_spacing', source)
        self.assertIn('default=6000', source)
        self.assertIn('default=2500', source)

    def test_viewer_defaults_to_solid_buildings_and_calculated_contours(self) -> None:
        source = VIEWER.read_text(encoding="utf-8")
        self.assertIn('value="solid" selected', source)
        self.assertIn('<option value="voxel" selected>Box/Voxel</option>', source)
        self.assertIn("function addVoxelSurface", source)
        self.assertIn("function drawVoxelCube", source)
        self.assertIn("data.modelVoxels", source)
        self.assertIn("frame.waveVoxels", source)
        self.assertIn('id="showGround"', source)
        self.assertIn('id="showX"', source)
        self.assertNotIn('id="showX" type="checkbox" checked', source)
        self.assertNotIn('id="showY" type="checkbox" checked', source)
        self.assertIn("addContourTriangles", source)
        self.assertIn("drawVoxelPlane", source)
        self.assertIn("ctx.globalAlpha=0.72", source)
        self.assertIn("3D overpressure shell จาก CFD", source)
        self.assertIn("mesh.op&&Number.isFinite(mesh.op[i])", source)
        self.assertIn("Number.isFinite(frame.stats.waveOpMin)", source)
        self.assertIn("const MAX_VOXEL_IMAGES = 16", source)
        self.assertIn("image.decoding='async'", source)
        self.assertIn("preloadFrame(index+1);preloadFrame(index+2)", source)
        self.assertIn("requestAnimationFrame(playbackTick)", source)
        self.assertNotIn("voxelImages.clear()", source)
        self.assertNotIn("setInterval(", source)
        self.assertIn("Object.assign({voxelPlane:true},item)", source)
        self.assertIn("drawConfiguredSources", source)
        self.assertIn("configuredSources.forEach", source)
        self.assertLess(
            source.index("Object.assign({voxelPlane:true},item)"),
            source.index("items.sort((a,b)=>a.depth-b.depth)"),
        )


if __name__ == "__main__":
    unittest.main()
