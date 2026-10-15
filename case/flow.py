"""Fluid-dynamics relief: streaklines of a Kármán vortex street, from a real 2-D simulation.

A D2Q9 lattice-Boltzmann solver (BGK collision, numpy) computes the unsteady flow past
a circular cylinder placed just below the camera collar. Flow runs down the phone
(top to bottom). Passive particles released from a rake upstream trace streaklines,
as smoke wires or dye ports do in a water tunnel. The streaklines, thickened to
printable ridges, become the plate's relief.

Results are cached in data/ (they take about a minute to compute).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import asdict, dataclass

import numpy as np
import shapely

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"

# D2Q9 lattice: velocities (streamwise s, cross-stream n), weights, opposites.
E = np.array([(0, 0), (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1)])
W = np.array([4 / 9] + [1 / 9] * 4 + [1 / 36] * 4)
OPP = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6])


@dataclass(frozen=True)
class Karman:
    """Flow past a cylinder. Lengths in mm on the plate; the cylinder centre is at (0, y_c)."""

    D: float = 10.0  # cylinder diameter
    y_c: float = 28.0  # cylinder centre (phone y)
    Re: float = 150.0
    dx: float = 0.5  # lattice spacing (mm)
    U: float = 0.1  # inflow speed, lattice units (Mach ~0.17)
    width: float = 150.0  # cross-stream domain (periodic), mm
    upstream: float = 40.0  # inlet distance above the cylinder centre, mm
    downstream: float = 170.0  # outlet distance below the cylinder centre, mm
    rake_y: float = 42.5  # streakline release line (phone y)
    rake_dx: float = 2.6  # spacing between streaklines, mm
    rake_x: float = 40.0  # rake spans -rake_x..rake_x
    port_angles: tuple[float, ...] = (95.0, 105.0, 115.0, 125.0)  # dye ports on the cylinder, deg from the front
    port_gap: float = 0.75  # ports sit this far outside the surface, mm
    spin_up: int = 16000  # steps before releasing dye
    release_steps: int = 7000  # steps of dye release (sets how far the streaklines reach)
    release_every: int = 2

    def key(self) -> str:
        return hashlib.sha1(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:10]


def _equilibrium(rho, us, un, out=None):
    """D2Q9 equilibrium; float32 throughout for speed."""
    usq = 1.5 * (us * us + un * un)
    out = np.empty((9,) + rho.shape, np.float32) if out is None else out
    for i in range(9):
        eu = E[i, 0] * us + E[i, 1] * un if i else 0.0
        out[i] = W[i] * rho * (1 + 3 * eu + 4.5 * eu * eu - usq)
    return out


def _bilinear(field, s, n):
    """Sample a (NS, NN) field at fractional cell positions; periodic in n."""
    NS, NN = field.shape
    s = np.clip(s, 0, NS - 1.001)
    s0 = np.floor(s).astype(int); n0 = np.floor(n).astype(int)
    ts = s - s0; tn = n - n0
    n0 %= NN; n1 = (n0 + 1) % NN
    f00 = field[s0, n0]; f10 = field[s0 + 1, n0]; f01 = field[s0, n1]; f11 = field[s0 + 1, n1]
    return (f00 * (1 - ts) * (1 - tn) + f10 * ts * (1 - tn) + f01 * (1 - ts) * tn + f11 * ts * tn)


def simulate(k: Karman, progress: bool = True) -> list[np.ndarray]:
    """Run the simulation; return streaklines as (N, 2) arrays of phone (x, y) in mm."""
    NS = int(round((k.upstream + k.downstream) / k.dx))
    NN = int(round(k.width / k.dx))
    sc, nc = k.upstream / k.dx, NN / 2 - 0.5  # cylinder centre in lattice units
    R = k.D / 2 / k.dx
    nu = k.U * (2 * R) / k.Re
    tau = 3 * nu + 0.5
    S, N = np.meshgrid(np.arange(NS), np.arange(NN), indexing="ij")
    solid = (S - sc) ** 2 + (N - nc) ** 2 <= R * R

    rho = np.ones((NS, NN), np.float32)
    us = np.full((NS, NN), k.U, np.float32)
    # Small antisymmetric kick behind the cylinder so shedding starts quickly.
    un = (0.02 * k.U * np.sin(2 * np.pi * (N - nc) / NN) * (S > sc)).astype(np.float32)
    us[solid] = 0; un[solid] = 0
    f = _equilibrium(rho, us, un)
    f_in = _equilibrium(np.ones((1, NN), np.float32), np.full((1, NN), k.U, np.float32), np.zeros((1, NN), np.float32))
    feq = np.empty_like(f)
    si, sj = np.nonzero(solid)

    # Seeds: the rake (offset by half a spacing so no particle sits on the stagnation
    # streamline) and dye ports on both shoulders of the cylinder.
    xs = np.arange(-k.rake_x + k.rake_dx / 2, k.rake_x, k.rake_dx)
    seeds = [("rake", x, (k.y_c - k.rake_y) / k.dx + sc, x / k.dx + nc) for x in xs]
    for ang in k.port_angles:
        for side in (-1, 1):
            a = np.radians(ang)
            r = R + k.port_gap / k.dx
            seeds.append((f"port{side * ang:+.0f}", side * ang, sc - r * np.cos(a), nc + side * r * np.sin(a)))
    seed_s = np.array([q[2] for q in seeds]); seed_n = np.array([q[3] for q in seeds])
    lines = [[] for _ in seeds]  # per seed: particle indices in release order
    ps = np.empty(0); pn = np.empty(0); alive = np.empty(0, bool)

    total = k.spin_up + k.release_steps
    for step in range(total):
        rho = f.sum(axis=0)
        us = (f[1] + f[5] + f[8] - f[3] - f[6] - f[7]) / rho
        un = (f[2] + f[5] + f[6] - f[4] - f[7] - f[8]) / rho
        us[si, sj] = 0; un[si, sj] = 0
        _equilibrium(rho, us, un, out=feq)
        wall = f[:, si, sj][OPP]  # bounce-back on the cylinder (reversed populations)
        f += (feq - f) / np.float32(tau)
        f[:, si, sj] = wall
        for i in range(1, 9):
            f[i] = np.roll(f[i], (E[i, 0], E[i, 1]), axis=(0, 1))
        f[:, 0, :] = f_in[:, 0, :]  # inlet: equilibrium at U
        f[:, -1, :] = f[:, -2, :]  # outlet: zero gradient

        if step >= k.spin_up:
            if (step - k.spin_up) % k.release_every == 0:
                base = len(ps)
                ps = np.concatenate([ps, seed_s])
                pn = np.concatenate([pn, seed_n])
                alive = np.concatenate([alive, np.ones(len(seeds), bool)])
                for j in range(len(seeds)):
                    lines[j].append(base + j)
            # Heun (RK2) advection with the current velocity field, dt = 1 step.
            a = alive
            v1s = _bilinear(us, ps[a], pn[a]); v1n = _bilinear(un, ps[a], pn[a])
            v2s = _bilinear(us, ps[a] + v1s, pn[a] + v1n); v2n = _bilinear(un, ps[a] + v1s, pn[a] + v1n)
            ps[a] += 0.5 * (v1s + v2s); pn[a] += 0.5 * (v1n + v2n)
            alive &= ps < NS - 2
        if progress and step % 2000 == 0:
            print(f"  LBM step {step}/{total}  max|u|={np.hypot(us, un).max():.3f}", flush=True)
        if not np.isfinite(f).all():
            raise FloatingPointError(f"LBM blew up at step {step} (tau={tau:.4f}); lower Re or refine dx")

    out = []
    for (kind, tag, _, _), idx in zip(seeds, lines):
        idx = np.array(idx)[::-1]  # oldest (furthest downstream) first
        x = (pn[idx] - nc) * k.dx
        y = k.y_c - (ps[idx] - sc) * k.dx
        out.append((kind, float(tag), np.c_[x, y]))
    return out


def streaklines(k: Karman = Karman()) -> list[tuple[str, float, np.ndarray]]:
    """(kind, tag, xy) per seed: kind 'rake' (tag = x of the release point) or 'port...' (tag = angle)."""
    cache = DATA / f"karman_{k.key()}.npz"
    if not cache.exists():
        print(f"simulating Kármán street (Re {k.Re:g}, D {k.D:g} mm); cached afterwards in {cache.name}", flush=True)
        lines = simulate(k)
        DATA.mkdir(exist_ok=True)
        np.savez_compressed(cache, n=len(lines), meta=json.dumps(asdict(k)),
                            kinds=np.array([q[0] for q in lines]), tags=np.array([q[1] for q in lines]),
                            **{f"l{i}": q[2] for i, q in enumerate(lines)})
    z = np.load(cache)
    return [(str(z["kinds"][i]), float(z["tags"][i]), z[f"l{i}"]) for i in range(int(z["n"]))]


def _pieces(xy: np.ndarray, max_gap: float) -> list[np.ndarray]:
    """Split a streakline wherever neighbouring particles are too far apart to join with a line
    (strong stretching, or particles held back behind the cylinder)."""
    d = np.hypot(*np.diff(xy, axis=0).T)
    cuts = np.where(d > max_gap)[0]
    return [seg for seg in np.split(xy, cuts + 1) if len(seg) >= 2]


def relief(region: shapely.Geometry, k: Karman = Karman(), width: float = 1.0, min_feature: float = 0.8,
           top_strip: shapely.Geometry | None = None, wake_clear: float = 7.5,
           ports: tuple[float, ...] = (105.0,), max_gap: float = 1.5) -> tuple[shapely.Geometry, shapely.Geometry]:
    """Dye ridges and the cylinder disc, clipped to `region`.

    Rake streaklines that start within `wake_clear` of the centre line would be swept into
    the wake and tangle, so the wake is drawn by dye released from the cylinder's shoulder
    ports at the given angles instead (the classic Taneda picture). `top_strip`, if given,
    gets straight lines that continue the rake upward, as if the flow passed behind the
    camera collar."""
    lines = []
    for kind, tag, xy in streaklines(k):
        if kind == "rake" and abs(tag) < wake_clear:
            continue
        if kind.startswith("port") and abs(tag) not in ports:
            continue
        for seg in _pieces(xy, max_gap):
            lines.append(shapely.LineString(seg))
    dye = shapely.unary_union([l.buffer(width / 2, quad_segs=4) for l in lines])
    if top_strip is not None:
        xs = np.arange(-k.rake_x + k.rake_dx / 2, k.rake_x, k.rake_dx)
        y0, y1 = top_strip.bounds[1] - 1, top_strip.bounds[3] + 1
        dye = dye.union(shapely.unary_union([shapely.LineString([(x, y0), (x, y1)]).buffer(width / 2) for x in xs]))
    cyl = shapely.Point(0, k.y_c).buffer(k.D / 2, quad_segs=32)
    r = min_feature / 2
    dye = dye.difference(cyl.buffer(0.6))  # a clear moat around the cylinder
    dye = dye.buffer(-r, quad_segs=4).buffer(r, quad_segs=4)  # drop slivers
    dye = dye.intersection(region).simplify(0.03)
    return dye, cyl.intersection(region)
