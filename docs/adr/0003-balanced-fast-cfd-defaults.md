# ADR 0003: Balanced-fast CFD defaults

## Context

A completed 100 kg reference job used 10 ranks, reached about 902,000 cells,
created 127 processor time directories, occupied 33 GiB, and spent 37,062 wall
seconds in blastFoam. Its final reported maximum Courant number was about
0.0218 against `maxCo=0.3`; the fixed `maxDeltaT=2.5e-7` ceiling, rather than
the Courant controller, forced roughly 50,000 timesteps. The Web exporter keeps
at most 48 frames, so writing 125 raw field snapshots also added I/O without
improving the delivered animation.

## Decision

Add a default `fast` profile named **Balanced Fast** and retain `quality` and
`custom` alternatives. Balanced Fast uses a 2 m base-cell target, automatic
building refinement, 3 million-cell safety caps, the existing `maxCo=0.3` and
initial timestep, `maxDeltaT=2e-6`, and approximately 48–50 output frames.

Keep only the latest two raw OpenFOAM write times with `purgeWrite 2`. Online
wall, iso-surface and pressure-slice function-object results remain at every
configured output time, so the scientific Web viewer keeps its temporal
series. Disable the unused dynamic-mesh level dump and package only the final
2 MiB of the solver log; the complete log remains in the server job.

The 2e-6 ceiling is below the approximately 3.4e-6 value obtained by linearly
scaling the measured final Courant number to 0.3. This is evidence for a
benchmark, not a guarantee: adaptive timestep control remains authoritative.

## Consequences

A completed like-for-like 100 kg, 10-rank, 0.0125 s comparison measured:

- blastFoam ClockTime: 37,062 s -> 3,114 s (11.9x faster);
- job bytes: 35,088,170,777 -> 1,295,237,587 (32.68 -> 1.21 GiB);
- timesteps: 50,005 -> 6,321; pressure-slice writes: 126 -> 49;
- initialised cells: 835,987 -> 502,902;
- final maximum Courant: 0.02179 -> 0.06766, below the unchanged 0.3 limit.

The display contract remained 48 browser frames, exact STL wall geometry and
0.1 m Cartesian display slices. This does **not** establish numerical
equivalence. At the same three probes, peak overpressure differed by -24.8%,
-26.2% and -10.8%; final impulse differed by -10.7%, -4.9% and +1.0% relative
to the 1.5 m reference. `fast` is therefore a screening/visualisation profile.
Engineering decisions based on peaks require `quality` or `custom` plus a
mesh-convergence study.

Raw intermediate time directories older than the two newest are intentionally
not retained. Probe histories, calculated surface time series, diagnostics and
the final Web result remain available. Existing cases are not rewritten.

## Alternatives

- Increase `maxCo`: rejected; the accepted stability control remains 0.3.
- Reduce the 0.1 m display grid: rejected because it would degrade the requested
  Box Voxel presentation without addressing solver runtime.
- Automatically delete complete jobs or post-processing data: rejected because
  deletion requires explicit user confirmation.
