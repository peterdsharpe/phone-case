"""Engineering cross-sections of phone + bumper + plate, for checking fit and profiles."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path  # noqa: E402

STYLE = {"phone": ("#8c9586", 0.9), "bumper": ("#303236", 0.95), "plate": ("#4a78a8", 0.9)}


def to_trimesh(shape, tol=0.02) -> trimesh.Trimesh:
    if isinstance(shape, trimesh.Trimesh):
        return shape
    v, t = shape.tessellate(tol, 0.15)
    return trimesh.Trimesh(np.array([(p.X, p.Y, p.Z) for p in v]), np.array(t), process=True)


def cut(m: trimesh.Trimesh, origin, normal, u_axis) -> shapely.Geometry:
    """Section of mesh `m` by a plane, returned in 2-D coordinates (u along u_axis, v along +z)."""
    normal = np.asarray(normal, float); u = np.asarray(u_axis, float)
    v = np.cross(normal, u)
    if v[2] < 0:
        v = -v
    s = m.section(plane_origin=origin, plane_normal=normal)
    if s is None:
        return shapely.Polygon()
    T = np.eye(4); T[:3, 0], T[:3, 1], T[:3, 2] = u, v, normal; T[:3, 3] = origin
    p2, _ = s.to_2D(to_2D=np.linalg.inv(T), check=False)
    polys = p2.polygons_full
    return shapely.unary_union(polys) if polys else shapely.Polygon()


def patch(geom, color, alpha, ax):
    for g in getattr(geom, "geoms", [geom]):
        if g.is_empty:
            continue
        verts, codes = [], []
        for ring in [g.exterior, *g.interiors]:
            xy = np.asarray(ring.coords)
            verts += list(xy); codes += [Path.MOVETO] + [Path.LINETO] * (len(xy) - 2) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), facecolor=color, edgecolor="k", lw=0.4, alpha=alpha))


def section_figure(meshes: dict[str, trimesh.Trimesh], views: list[dict], path: str, title: str = ""):
    """views: dicts with keys name, origin, normal, u, xlim, ylim."""
    n = len(views)
    cols = 2
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(7.5 * cols, 4.2 * rows))
    for ax, vw in zip(np.atleast_1d(axes).ravel(), views):
        for key, m in meshes.items():
            g = cut(m, vw["origin"], vw["normal"], vw["u"])
            col, a = STYLE.get(key, ("#999", 0.8))
            patch(g, col, a, ax)
        ax.set_xlim(*vw["xlim"]); ax.set_ylim(*vw["ylim"])
        ax.set_aspect("equal"); ax.grid(True, lw=0.3, alpha=0.6)
        ax.set_title(vw["name"], fontsize=10)
        ax.set_xlabel("mm"); ax.set_ylabel("z (mm)")
    for ax in np.atleast_1d(axes).ravel()[n:]:
        ax.axis("off")
    if title:
        fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
