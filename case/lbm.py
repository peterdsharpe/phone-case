"""2-D lattice-Boltzmann solver (D2Q9, regularized BGK, numba) for flow past the camera collar.

The back of the phone is treated as a window into an open flow: the lattice is
several collar-widths wide (periodic sides) so the wake is not confined. Inflow
enters at the phone's top edge and leaves past the bottom. Velocity snapshots
over the phone window are saved over one shedding cycle.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import asdict, dataclass

import numba as nb
import numpy as np

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"

CX = np.array([0, 1, 0, -1, 0, 1, -1, -1, 1], np.int64)
CY = np.array([0, 0, 1, 0, -1, 1, 1, -1, -1], np.int64)
WT = np.array([4 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 36, 1 / 36, 1 / 36, 1 / 36])
OPP = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6], np.int64)


@nb.njit(parallel=True, fastmath=True, cache=True)
def _step(f, fn, solid, omega, u_in, j_sponge, sigma):
    """One fused pull-stream + regularized-BGK collide step.

    Lattice axes: i = cross-stream (periodic), j = streamwise (flow toward +j).
    Inlet at j = 0 (equilibrium at u_in), zero-gradient outlet at j = NJ-1,
    half-way bounce-back on solid cells. Rows past j_sponge relax toward the uniform
    inflow (strength ramping up to sigma) so vortices die before the outlet."""
    NI, NJ = solid.shape
    f0 = np.empty(9)
    for q in range(9):
        cu = 3.0 * (CY[q] * u_in)
        f0[q] = WT[q] * (1.0 + cu + 0.5 * cu * cu - 1.5 * u_in * u_in)
    for i in nb.prange(NI):
        g = np.empty(9)
        for j in range(NJ):
            if solid[i, j]:
                for q in range(9):
                    fn[q, i, j] = WT[q]
                continue
            for q in range(9):
                si = (i - CX[q]) % NI
                sj = j - CY[q]
                if sj < 0:  # from the inlet: equilibrium population
                    cu = 3.0 * (CY[q] * u_in)
                    g[q] = WT[q] * (1.0 + cu + 0.5 * cu * cu - 1.5 * u_in * u_in)
                elif sj >= NJ:  # from beyond the outlet: zero gradient
                    g[q] = f[q, i, j]
                elif solid[si, sj]:  # bounce-back
                    g[q] = f[OPP[q], i, j]
                else:
                    g[q] = f[q, si, sj]
            rho = 0.0; ux = 0.0; uy = 0.0
            for q in range(9):
                rho += g[q]; ux += g[q] * CX[q]; uy += g[q] * CY[q]
            ux /= rho; uy /= rho
            usq = 1.5 * (ux * ux + uy * uy)
            pxx = 0.0; pyy = 0.0; pxy = 0.0
            feq = np.empty(9)
            for q in range(9):
                cu = 3.0 * (CX[q] * ux + CY[q] * uy)
                feq[q] = WT[q] * rho * (1.0 + cu + 0.5 * cu * cu - usq)
                d = g[q] - feq[q]
                pxx += d * CX[q] * CX[q]; pyy += d * CY[q] * CY[q]; pxy += d * CX[q] * CY[q]
            sg = 0.0
            if j > j_sponge:
                r = (j - j_sponge) / (NJ - j_sponge)
                sg = sigma * r * r
            for q in range(9):
                qxx = CX[q] * CX[q] - 1.0 / 3.0; qyy = CY[q] * CY[q] - 1.0 / 3.0; qxy = CX[q] * CY[q]
                fneq = WT[q] * 4.5 * (qxx * pxx + qyy * pyy + 2.0 * qxy * pxy)
                post = feq[q] + (1.0 - omega) * fneq
                fn[q, i, j] = post - sg * (post - f0[q])


@nb.njit(parallel=True, cache=True)
def _velocity(f, solid, ux, uy):
    NI, NJ = solid.shape
    for i in nb.prange(NI):
        for j in range(NJ):
            rho = 0.0; a = 0.0; b = 0.0
            for q in range(9):
                rho += f[q, i, j]; a += f[q, i, j] * CX[q]; b += f[q, i, j] * CY[q]
            if solid[i, j]:
                ux[i, j] = 0.0; uy[i, j] = 0.0
            else:
                ux[i, j] = a / rho; uy[i, j] = b / rho


@dataclass(frozen=True)
class Wake:
    """Flow past the camera collar. Lengths in mm; Re is based on the collar width."""

    Re: float = 1000.0
    dx: float = 0.5
    U: float = 0.05  # lattice inflow speed; peaks near 1.8 U around the collar ends
    sponge: float = 100.0  # mm before the outlet where the wake is damped
    sponge_sigma: float = 0.05
    width_mult: float = 6.0  # domain width in collar widths
    upstream: float = 150.0  # inlet distance above the phone's top edge
    downstream: float = 220.0  # outlet distance below the phone's bottom edge
    periods_spin_up: float = 5.0
    kick: float = 0.3  # initial sideways velocity behind the body, in units of U
    snapshots: int = 16  # snapshots over one shedding period
    strouhal_guess: float = 0.16

    def key(self, body: str) -> str:
        return hashlib.sha1((json.dumps(asdict(self), sort_keys=True) + body).encode()).hexdigest()[:10]


def run(w: Wake, body_mask_fn, window: tuple[float, float, float, float], body_width: float,
        progress: bool = True) -> dict:
    """Simulate; return snapshots of (ux, uy) over `window` = (x0, x1, y0, y1) in phone mm.

    body_mask_fn(X, Y) -> bool array marks the obstacle at phone coordinates."""
    x0, x1, y0, y1 = window
    W_dom = w.width_mult * body_width
    NI = int(round(W_dom / w.dx))
    j_top = y1 + w.upstream  # phone y of the inlet
    NJ = int(round((w.upstream + (y1 - y0) + w.downstream) / w.dx))
    xs = (np.arange(NI) - (NI - 1) / 2) * w.dx  # phone x of lattice column i
    ys = j_top - np.arange(NJ) * w.dx  # phone y of lattice row j (flow toward -y)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    solid = body_mask_fn(X, Y)
    D = body_width / w.dx
    nu = w.U * D / w.Re
    omega = 1.0 / (3 * nu + 0.5)
    f = np.empty((9, NI, NJ))
    # Uniform flow plus a one-sided sideways push in the near wake: a symmetric start on a
    # symmetric grid would otherwise keep a steady, symmetric bubble for a very long time.
    yb = Y[solid].min()
    uy = w.U * np.ones((NI, NJ))
    ux = w.kick * w.U * ((np.abs(X) < body_width / 2) & (Y < yb) & (Y > yb - body_width))
    for q in range(9):
        cu = 3 * (CX[q] * ux + CY[q] * uy)
        f[q] = WT[q] * (1 + cu + 0.5 * cu * cu - 1.5 * (ux * ux + uy * uy))
    fn = np.empty_like(f)
    j_sponge = NJ - int(w.sponge / w.dx)
    assert ys[j_sponge] < y0 - 50, "sponge too close to the phone window"
    period = D / (w.strouhal_guess * w.U)
    n_spin = int(w.periods_spin_up * period)
    every = max(1, int(period / w.snapshots))
    n_total = n_spin + every * w.snapshots
    ii = np.where((xs >= x0 - w.dx) & (xs <= x1 + w.dx))[0]
    jj = np.where((ys >= y0 - w.dx) & (ys <= y1 + w.dx))[0]
    ux = np.empty((NI, NJ)); uy = np.empty((NI, NJ))
    shots = []
    probe = []  # cross-stream velocity behind the body, to measure the real period
    pi_, pj = NI // 2, int(np.argmin(np.abs(ys - (y0 + 0.3 * (y1 - y0)))))
    for n in range(n_total):
        _step(f, fn, solid, omega, w.U, j_sponge, w.sponge_sigma)
        f, fn = fn, f
        snap = n >= n_spin and (n - n_spin) % every == 0
        if n % 50 == 0 or snap:
            _velocity(f, solid, ux, uy)
            if n % 50 == 0:
                probe.append((n, ux[pi_, pj]))
            if snap:
                shots.append(np.stack([ux[np.ix_(ii, jj)], -uy[np.ix_(ii, jj)]]).astype(np.float32))  # phone (vx, vy)
        if progress and n % 5000 == 0:
            _velocity(f, solid, ux, uy)
            sp = np.hypot(ux, uy)
            print(f"  step {n}/{n_total}  max|u|/U = {sp.max() / w.U:.2f}", flush=True)
            if not np.isfinite(sp).all():
                raise FloatingPointError("LBM diverged")
    return dict(xs=xs[ii], ys=ys[jj], shots=np.stack(shots), probe=np.array(probe), period_guess=period,
                every=every, U=w.U, omega=omega, grid=(NI, NJ))


def cached(w: Wake, body_mask_fn, body_tag: str, window, body_width) -> dict:
    path = DATA / f"wake_{w.key(body_tag)}.npz"
    if not path.exists():
        print(f"LBM: Re {w.Re:g}, collar {body_width:.1f} mm wide; caching to {path.name}", flush=True)
        r = run(w, body_mask_fn, window, body_width)
        DATA.mkdir(exist_ok=True)
        np.savez_compressed(path, meta=json.dumps(asdict(w)), **{k: np.asarray(v) for k, v in r.items()})
    z = np.load(path)
    return {k: z[k] for k in z.files}
