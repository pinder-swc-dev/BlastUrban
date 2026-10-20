import math, tempfile, unittest
from pathlib import Path
import cfd_verify as v


class ExactSod(unittest.TestCase):
    def test_star_state_matches_toro_table(self):
        # Toro Test 1: p* = 0.30313, u* = 0.92745
        (_, u, p), = v.sod_exact([0.5 + 0.9274 * 0.2 * 0.5], 0.2)  # inside star-left region
        self.assertAlmostEqual(p, 0.30313, places=4)
        self.assertAlmostEqual(u, 0.92745, places=4)

    def test_far_field_untouched(self):
        a, b = v.sod_exact([0.0, 1.0], 0.2)
        self.assertEqual(a, (1.0, 0.0, 1.0))
        self.assertEqual(b, (0.125, 0.0, 0.1))

    def test_rankine_hugoniot_mass_flux_across_shock(self):
        g, t = 1.4, 0.2
        # locate the shock numerically from the exact profile
        xs = [0.5 + i * 1e-4 for i in range(1, 5000)]
        prof = v.sod_exact(xs, t)
        i = max(range(len(prof) - 1), key=lambda k: prof[k][2] - prof[k + 1][2])
        shock_speed = (xs[i] - 0.5) / t
        r1, u1, _ = prof[i]
        r2, u2, _ = prof[i + 1]
        self.assertAlmostEqual(r1 * (u1 - shock_speed), r2 * (u2 - shock_speed), delta=2e-3)

    def test_total_mass_conserved_with_exact_solution(self):
        n = 4000
        xs = [(i + 0.5) / n for i in range(n)]
        prof = v.sod_exact(xs, 0.1)
        mass = sum(r for r, _, _ in prof) / n
        self.assertAlmostEqual(mass, 0.5 * 1.0 + 0.5 * 0.125, places=3)


class Helpers(unittest.TestCase):
    def test_observed_order(self):
        self.assertAlmostEqual(v.observed_order(0.04, 0.01), 2.0)

    def test_finite_positive_detects_problems(self):
        self.assertEqual(v.check_finite_positive("p", [1.0, 2.0]), [])
        self.assertTrue(v.check_finite_positive("p", [1.0, float("nan")]))
        self.assertTrue(v.check_finite_positive("p", [1.0, -1.0]))

    def test_parse_nonuniform_and_uniform(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d, "p")
            a.write_text("internalField nonuniform List<scalar> 3\n(\n1e5\n2.5e5\n-3\n)\n;\n")
            self.assertEqual(v.read_internal_scalar(a), [1e5, 2.5e5, -3.0])
            b = Path(d, "T")
            b.write_text("internalField uniform 300;\n")
            self.assertEqual(v.read_internal_scalar(b), [300.0])

    def test_conserved_totals_uniform_gas(self):
        m, q, e = v.conserved_totals([1, 1], [2, 2], [1.4, 1.4], [0.5, 0.5], 1.4)
        self.assertAlmostEqual(m, 1.0)
        self.assertAlmostEqual(q, 2.0)
        self.assertAlmostEqual(e, 1.4 / 0.4 + 0.5 * 4)


if __name__ == "__main__":
    unittest.main()
