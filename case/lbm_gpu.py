"""CUDA versions of the lattice-Boltzmann kernels in case/lbm.py (numba-cuda, float32).

The RTX-class GPUs run float64 at a small fraction of float32 speed, so every constant
and argument here is float32."""

from __future__ import annotations

import math

import numpy as np

if not hasattr(np, "row_stack"):  # numba-cuda 0.30.4 still overloads np.row_stack, removed in NumPy 2.5
    np.row_stack = np.vstack

from numba import cuda, float32, int32  # noqa: E402

CX = np.array([0, 1, 0, -1, 0, 1, -1, -1, 1], np.int32)
CY = np.array([0, 0, 1, 0, -1, 1, 1, -1, -1], np.int32)
WT = np.array([4 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 36, 1 / 36, 1 / 36, 1 / 36], np.float32)
OPP = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6], np.int32)


@cuda.jit(fastmath=True)
def step(f, fn, solid, omega, u_in, j_sponge, sigma, cs2):
    """One fused pull-stream + regularized-BGK (+ Smagorinsky) step; see lbm._step."""
    j, i = cuda.grid(2)  # j (contiguous axis) varies fastest across threads
    NI = solid.shape[0]
    NJ = solid.shape[1]
    if i >= NI or j >= NJ:
        return
    one = float32(1.0)
    three = float32(3.0)
    half = float32(0.5)
    if solid[i, j]:
        for q in range(9):
            fn[q, i, j] = WT[q]
        return
    g = cuda.local.array(9, float32)
    feq = cuda.local.array(9, float32)
    for q in range(9):
        si = (i - CX[q]) % NI
        sj = j - CY[q]
        if sj < 0:
            cu = three * (float32(CY[q]) * u_in)
            g[q] = WT[q] * (one + cu + half * cu * cu - float32(1.5) * u_in * u_in)
        elif sj >= NJ:
            g[q] = f[q, i, j]
        elif solid[si, sj]:
            g[q] = f[OPP[q], i, j]
        else:
            g[q] = f[q, si, sj]
    rho = float32(0.0)
    ux = float32(0.0)
    uy = float32(0.0)
    for q in range(9):
        rho += g[q]
        ux += g[q] * float32(CX[q])
        uy += g[q] * float32(CY[q])
    ux /= rho
    uy /= rho
    usq = float32(1.5) * (ux * ux + uy * uy)
    pxx = float32(0.0)
    pyy = float32(0.0)
    pxy = float32(0.0)
    for q in range(9):
        cx = float32(CX[q])
        cy = float32(CY[q])
        cu = three * (cx * ux + cy * uy)
        feq[q] = WT[q] * rho * (one + cu + half * cu * cu - usq)
        d = g[q] - feq[q]
        pxx += d * cx * cx
        pyy += d * cy * cy
        pxy += d * cx * cy
    om = omega
    if cs2 > float32(0.0):
        tau0 = one / omega
        Q = math.sqrt(pxx * pxx + pyy * pyy + float32(2.0) * pxy * pxy)
        om = float32(2.0) / (tau0 + math.sqrt(tau0 * tau0 + float32(25.455844122715714) * cs2 * Q / rho))
    sg = float32(0.0)
    if j > j_sponge:
        r = float32(j - j_sponge) / float32(NJ - j_sponge)
        sg = sigma * r * r
    third = float32(1.0 / 3.0)
    for q in range(9):
        cx = float32(CX[q])
        cy = float32(CY[q])
        fneq = WT[q] * float32(4.5) * ((cx * cx - third) * pxx + (cy * cy - third) * pyy + float32(2.0) * cx * cy * pxy)
        post = feq[q] + (one - om) * fneq
        cu = three * (cy * u_in)
        f0 = WT[q] * (one + cu + half * cu * cu - float32(1.5) * u_in * u_in)
        fn[q, i, j] = post - sg * (post - f0)


@cuda.jit(fastmath=True)
def velocity(f, solid, ux, uy):
    j, i = cuda.grid(2)
    NI = solid.shape[0]
    NJ = solid.shape[1]
    if i >= NI or j >= NJ:
        return
    if solid[i, j]:
        ux[i, j] = float32(0.0)
        uy[i, j] = float32(0.0)
        return
    rho = float32(0.0)
    a = float32(0.0)
    b = float32(0.0)
    for q in range(9):
        v = f[q, i, j]
        rho += v
        a += v * float32(CX[q])
        b += v * float32(CY[q])
    ux[i, j] = a / rho
    uy[i, j] = b / rho


@cuda.jit(device=True, inline=True)
def _cr(t, a, b, c, d):
    return b + float32(0.5) * t * (c - a + t * (float32(2.0) * a - float32(5.0) * b + float32(4.0) * c - d
                                                + t * (float32(3.0) * (b - c) + d - a)))


@cuda.jit(fastmath=True)
def advect(c, cn, ux, uy, dt, c_in):
    """Semi-Lagrangian bicubic advection of the dye label, clamped; see lbm._advect."""
    j, i = cuda.grid(2)
    NI = c.shape[0]
    NJ = c.shape[1]
    if i >= NI or j >= NJ:
        return
    if j == 0:
        cn[i, j] = c_in[i]
        return
    x = float32(i) - ux[i, j] * dt
    y = float32(j) - uy[i, j] * dt
    y = min(max(y, float32(0.0)), float32(NJ) - float32(1.000001))
    i0 = int32(math.floor(x))
    j0 = int32(y)
    tx = x - float32(i0)
    ty = y - float32(j0)
    rows = cuda.local.array(4, float32)
    lo = float32(1e30)
    hi = float32(-1e30)
    for m in range(4):
        jj = min(max(j0 - 1 + m, 0), NJ - 1)
        a = c[(i0 - 1) % NI, jj]
        b = c[i0 % NI, jj]
        cc = c[(i0 + 1) % NI, jj]
        d = c[(i0 + 2) % NI, jj]
        rows[m] = _cr(tx, a, b, cc, d)
        if m == 1 or m == 2:
            lo = min(lo, min(b, cc))
            hi = max(hi, max(b, cc))
    v = _cr(ty, rows[0], rows[1], rows[2], rows[3])
    cn[i, j] = min(max(v, lo), hi)


class Backend:
    """Device arrays and kernel launches for lbm.run."""

    def __init__(self, f, solid, c, c_in):
        self.NI, self.NJ = solid.shape
        self.f = cuda.to_device(f.astype(np.float32))
        self.fn = cuda.device_array_like(self.f)
        self.solid = cuda.to_device(solid.astype(np.uint8))
        self.c = cuda.to_device(c.astype(np.float32))
        self.cn = cuda.device_array_like(self.c)
        self.c_in = cuda.to_device(c_in.astype(np.float32))
        self.ux = cuda.device_array((self.NI, self.NJ), np.float32)
        self.uy = cuda.device_array((self.NI, self.NJ), np.float32)
        self.block = (32, 8)
        self.grid = ((self.NJ + 31) // 32, (self.NI + 7) // 8)

    def step(self, omega, u_in, j_sponge, sigma, cs2):
        step[self.grid, self.block](self.f, self.fn, self.solid, np.float32(omega), np.float32(u_in),
                                    np.int32(j_sponge), np.float32(sigma), np.float32(cs2))
        self.f, self.fn = self.fn, self.f

    def velocity(self):
        velocity[self.grid, self.block](self.f, self.solid, self.ux, self.uy)

    def advect(self, dt):
        advect[self.grid, self.block](self.c, self.cn, self.ux, self.uy, np.float32(dt), self.c_in)
        self.c, self.cn = self.cn, self.c

    def host(self, name):
        return getattr(self, name).copy_to_host()

    def probe(self, i, j):
        return float(self.ux[i, j])
