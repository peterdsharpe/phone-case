# Notes for agents working on this repository

- **Check every flow simulation spectrally before using it.** Grid-scale instability
  (checkerboarding, odd-even noise) in the lattice-Boltzmann solve looks like texture in the
  renders and is easy to miss. Compute FFT shell spectra of vorticity and divergence at lattice
  resolution, look at the 2-D spectrum for spikes on the axes or corners, and map the high-pass
  residual to see where any noise lives. A healthy 2-D run has an enstrophy spectrum that falls
  steeply (about k^-3 or faster) to the grid scale and almost no divergence; a flattened or
  bumped spectrum near Nyquist, or divergence that grows with k, means instability.
  `case/spectra.py` holds the metrics and limits, `lbm.run` records them for every snapshot,
  the build refuses a failing snapshot and writes `out/renders/flow_spectra.png`, and
  `.scratch/tools/spectra.py` is the fuller interactive check (2-D spectrum, residual map).
- **Look at renders critically** for numerical artifacts before presenting them, and explain
  any pattern that is not physics.
- **GPU:** the LBM runs on a CUDA GPU through numba-cuda when one is available
  (`uv sync --extra gpu`), and on the CPU otherwise. A default run needs under 1.5 GB of GPU
  memory; check free memory with `nvidia-smi` before larger grids.
