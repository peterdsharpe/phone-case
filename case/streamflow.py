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


def wake(p: Phone, c: Case, w: lbm.Wake = lbm.Wake()) -> dict:
    L, H = collar_size(p, c)
    window = (-p.W / 2, p.W / 2, -p.L / 2, p.L / 2)
    tag = f"collar {L:.3f}x{H:.3f}@{p.cam_y:.3f} window {window}"
    return lbm.cached(w, lambda X, Y: collar_mask(p, c, X, Y), tag, window, L)
