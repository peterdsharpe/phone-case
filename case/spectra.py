"""Spectral health check of a flow snapshot: catches grid-scale instability (checkerboarding).

A healthy 2-D large-eddy simulation has a vorticity (enstrophy) spectrum that falls steeply
toward the grid scale and almost no divergence: the lattice is weakly compressible, and its
acoustic content sits at large scales. Grid-scale noise shows as a flattened or bumped
enstrophy spectrum near the Nyquist wavenumber and as divergence that grows with k.

Metrics, over a fluid-only window with a Hann taper:
- div_ratio: variance of the divergence over that of the vorticity. Healthy runs: ~1e-4.
- hi_mid: mean enstrophy in 0.6-1.0 k_nyq over that in 0.15-0.3 k_nyq. Healthy: ~1e-3.
- bump: the enstrophy spectrum has a local maximum above 0.3 k_nyq.
The thresholds below were calibrated on the clean Re 1e4 run and the noisy Re 3e4 run
(div_ratio 4e-3 to 2e-2, hi_mid up to 0.9) of 2026-10-15.
"""

from __future__ import annotations

import numpy as np

LIMITS = dict(div_ratio=1e-3, hi_mid=1e-2)


def shell(F2: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray]:
    """Shell-averaged power of a 2-D FFT |F|^2 on a grid of pitch h."""
    kx = 2 * np.pi * np.fft.fftfreq(F2.shape[0], h)
    ky = 2 * np.pi * np.fft.fftfreq(F2.shape[1], h)
    K = np.hypot(*np.meshgrid(kx, ky, indexing="ij"))
    dk = max(kx[1] - kx[0], ky[1] - ky[0])
    bins = np.arange(0, np.pi / h + dk, dk)
    idx = np.digitize(K.ravel(), bins)
    s = np.bincount(idx, F2.ravel(), minlength=len(bins) + 1)[1:len(bins)]
    n = np.bincount(idx, minlength=len(bins) + 1)[1:len(bins)]
    return bins[:-1] + dk / 2, s / np.maximum(n, 1)


def fields(u: np.ndarray, v: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray]:
    """Vorticity and divergence of (u, v)[ix, iy] on a grid of pitch h (ascending axes)."""
    om = np.gradient(v, h, axis=0) - np.gradient(u, h, axis=1)
    dv = np.gradient(u, h, axis=0) + np.gradient(v, h, axis=1)
    return om, dv


def spectra(u: np.ndarray, v: np.ndarray, h: float) -> dict:
    """Shell spectra of vorticity and divergence and the health metrics."""
    om, dv = fields(u, v, h)
    T = np.outer(np.hanning(om.shape[0]), np.hanning(om.shape[1]))
    k, Z = shell(np.abs(np.fft.fft2((om - om.mean()) * T)) ** 2, h)
    _, D = shell(np.abs(np.fft.fft2((dv - dv.mean()) * T)) ** 2, h)
    knyq = np.pi / h
    hi = (k > 0.6 * knyq); mid = (k > 0.15 * knyq) & (k < 0.3 * knyq)
    # A pile-up: the smoothed tail rises 2x above its running minimum, at a level that matters
    # (above 1e-5 of the peak: lower than that is the float32 noise floor of a clean run).
    tail = Z[(k > 0.3 * knyq) & (Z > 1e-5 * Z.max())]
    if len(tail) > 4:
        ls = np.convolve(np.log(tail), np.ones(3) / 3, mode="valid")
        bump = bool(np.max(ls - np.minimum.accumulate(ls)) > np.log(2.0))
    else:
        bump = False
    return dict(k=k, Z=Z, D=D, div_ratio=float(dv.var() / max(om.var(), 1e-30)),
                hi_mid=float(Z[hi].mean() / max(Z[mid].mean(), 1e-30)), bump=bump)


def healthy(m: dict) -> bool:
    return m["div_ratio"] < LIMITS["div_ratio"] and m["hi_mid"] < LIMITS["hi_mid"] and not m["bump"]


def describe(m: dict) -> str:
    return (f"divergence/vorticity variance {m['div_ratio']:.1e} (limit {LIMITS['div_ratio']:.0e}), "
            f"enstrophy high/mid band {m['hi_mid']:.1e} (limit {LIMITS['hi_mid']:.0e}), "
            f"bump near Nyquist: {'yes' if m['bump'] else 'no'}")


def from_snapshot(r: dict) -> dict:
    """Metrics for a stored snapshot: the full-resolution ones recorded during the run, or
    (older snapshots) ones computed from the stored, block-averaged fields."""
    if "spec_div_ratio" in r and len(r["spec_div_ratio"]):
        return dict(k=r["spec_k"], Z=r["spec_Z"][0], D=r["spec_D"][0], div_ratio=float(r["spec_div_ratio"][0]),
                    hi_mid=float(r["spec_hi_mid"][0]), bump=bool(r["spec_bump"][0]), source="lattice")
    xs, ys = r["xs"].astype(float), r["ys"].astype(float)
    v = r["shots"][0].astype(float) / float(r["U"])
    if ys[0] > ys[-1]:
        ys, v = ys[::-1], v[:, :, ::-1]
    i = (xs > xs[0] + 3) & (xs < xs[-1] - 3)
    j = (ys > ys[0] + 3) & (ys < 38.0)  # below the collar
    return spectra(v[0][np.ix_(i, j)], v[1][np.ix_(i, j)], xs[1] - xs[0]) | dict(source="stored")
