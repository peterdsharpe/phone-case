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


SIDE_MARGIN = 16.0  # mm of flow stored beyond each long edge (the side bands need ~13)
END_MARGIN = 3.0  # ...and beyond each end: the fused case's back reaches 1.5 mm past the phone. Storage only:
#   the lattice is placed from the window's ends, so widening the window itself would change the flow.


def _tag(p: Phone, c: Case) -> tuple[str, tuple, float]:
    L, H = collar_size(p, c)
    m = SIDE_MARGIN  # past the phone's long edges: the flow there is folded onto the bumper's sides
    window = (-p.W / 2 - m, p.W / 2 + m, -p.L / 2, p.L / 2)
    return f"collar {L:.3f}x{H:.3f}@{p.cam_y:.3f} window {window} pad {END_MARGIN}", window, L


def wake(p: Phone, c: Case, w: lbm.Wake = lbm.Wake()) -> dict:
    """All snapshots of the flow (cached in data/wake_<key>.npz, not committed: 20 MB)."""
    tag, window, L = _tag(p, c)
    return lbm.cached(w, lambda X, Y: collar_mask(p, c, X, Y), tag, window, L, pad_y=END_MARGIN)


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
