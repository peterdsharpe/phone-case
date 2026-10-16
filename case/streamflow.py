"""Flow past the camera collar, for the streamline top layer."""

from __future__ import annotations

import numpy as np

from case import lbm
from case.params import Case, Phone
from case.plate import collar_size


def collar_mask(p: Phone, c: Case, X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Points inside the collar's stadium outline (phone mm)."""
    L, H = collar_size(p, c)
    r = H / 2
    dx = np.clip(np.abs(X) - (L / 2 - r), 0, None)
    return dx ** 2 + (Y - p.cam_y) ** 2 <= r ** 2


def _tag(p: Phone, c: Case) -> tuple[str, tuple, float]:
    L, H = collar_size(p, c)
    window = (-p.W / 2, p.W / 2, -p.L / 2, p.L / 2)
    return f"collar {L:.3f}x{H:.3f}@{p.cam_y:.3f} window {window}", window, L


def wake(p: Phone, c: Case, w: lbm.Wake = lbm.Wake()) -> dict:
    """All snapshots of the flow (cached in data/wake_<key>.npz, not committed: 20 MB)."""
    tag, window, L = _tag(p, c)
    return lbm.cached(w, lambda X, Y: collar_mask(p, c, X, Y), tag, window, L)


def snapshot(p: Phone, c: Case, phase: int, w: lbm.Wake = lbm.Wake()) -> dict:
    """One snapshot, with shots/dye of length 1. data/snap_<key>_<phase>.npz is small and
    committed, so the default design builds without re-running the flow."""
    tag, _, _ = _tag(p, c)
    path = lbm.DATA / f"snap_{w.key(tag)}_{phase}.npz"
    if not path.exists():
        r = wake(p, c, w)
        per = {k: r[k][phase:phase + 1] for k in r if k.startswith("spec_") and k != "spec_k"}
        np.savez_compressed(path, xs=r["xs"], ys=r["ys"], U=r["U"], shots=r["shots"][phase:phase + 1],
                            dye=r["dye"][phase:phase + 1], spec_k=r.get("spec_k", np.zeros(0)), **per)
    z = np.load(path)
    return {k: z[k] for k in z.files}
