"""Topographic relief for the back plate: a heightmap cut into stacked terraces.

Each terrace is one print layer tall, so the printer's layer lines become the
map's contour lines. Heightmaps come from real elevation data (AWS Terrain
Tiles, cached under data/) or from a procedural fractal.

Orientation: the map reads north-up, not mirrored, when you look at the back of
the phone with the camera at the top. Seen from the back, phone +x points left,
so map east = phone -x.
"""

from __future__ import annotations

import io
import json
import math
import pathlib
import subprocess

import contourpy
import numpy as np
import shapely
from scipy import ndimage

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

# Named places: (lat, lon of the map centre, map width in km east-west).
PLACES = {
    "rainier": (46.900, -121.7604, 26.0),  # summit sits low on the plate, below the camera
    "half-dome": (37.744, -119.56, 9.0),
    "matterhorn": (45.976, 7.66, 9.0),
    "fuji": (35.36, 138.73, 24.0),
    "mt-washington": (44.27, -71.30, 14.0),
    "grand-canyon": (36.10, -112.10, 20.0),
}


# --- heightmaps -----------------------------------------------------------------------------

def procedural(xs: np.ndarray, ys: np.ndarray, seed: int = 7, beta: float = 3.2, scale: float = 60.0) -> np.ndarray:
    """Fractal terrain (power-law spectrum, exponent `beta`) on the grid xs x ys (mm)."""
    rng = np.random.default_rng(seed)
    ny, nx = len(ys), len(xs)
    dx = (xs[-1] - xs[0]) / (nx - 1)
    kx = np.fft.fftfreq(nx, dx)[None, :]
    ky = np.fft.fftfreq(ny, dx)[:, None]
    k = np.hypot(kx, ky)
    k[0, 0] = np.inf
    amp = (k * scale) ** (-beta / 2)
    spec = amp * np.exp(2j * np.pi * rng.random((ny, nx)))
    h = np.real(np.fft.ifft2(spec))
    return (h - h.min()) / (h.max() - h.min())


def _tile(z: int, x: int, y: int) -> np.ndarray:
    import matplotlib.image as mpimg

    cache = DATA / "tiles" / f"{z}_{x}_{y}.png"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-sfL", "--retry", "4", "--retry-all-errors", "--retry-delay", "1", "-m", "30", "-o", str(cache), TILE_URL.format(z=z, x=x, y=y)], check=True)
    rgb = np.round(mpimg.imread(cache)[..., :3] * 255.0)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def dem(xs: np.ndarray, ys: np.ndarray, lat: float, lon: float, width_km: float, zoom: int | None = None) -> np.ndarray:
    """Real elevation (m) sampled on the plate grid. The grid's x span maps to `width_km`.
    By default the tile zoom is the coarsest whose pixels are no larger than a grid cell."""
    span_x = xs[-1] - xs[0]
    km_per_mm = width_km / span_x
    if zoom is None:
        cell_km = (xs[1] - xs[0]) * km_per_mm
        zoom = math.ceil(math.log2(40075 * math.cos(math.radians(lat)) / (256 * cell_km)))
    X, Y = np.meshgrid(xs, ys)
    east_km = -X * km_per_mm  # seen from the back, phone -x is east
    north_km = Y * km_per_mm
    lat_g = lat + north_km / 111.32
    lon_g = lon + east_km / (111.32 * math.cos(math.radians(lat)))
    n = 2 ** zoom
    gx = (lon_g + 180) / 360 * n * 256
    gy = (1 - np.arcsinh(np.tan(np.radians(lat_g))) / math.pi) / 2 * n * 256
    tx0, tx1 = int(gx.min() // 256), int(gx.max() // 256)
    ty0, ty1 = int(gy.min() // 256), int(gy.max() // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = _tile(zoom, tx, ty)
    return ndimage.map_coordinates(mosaic, [gy - ty0 * 256, gx - tx0 * 256], order=1, mode="nearest")


def heightmap(source: str, xs: np.ndarray, ys: np.ndarray, smooth_mm: float = 0.6) -> np.ndarray:
    """`source` is a key of PLACES, 'lat,lon,width_km', or 'procedural[:seed]'."""
    if source.startswith("procedural"):
        seed = int(source.split(":")[1]) if ":" in source else 7
        h = procedural(xs, ys, seed=seed)
    else:
        if source in PLACES:
            lat, lon, w = PLACES[source]
        else:
            lat, lon, w = (float(v) for v in source.split(","))
        h = dem(xs, ys, lat, lon, w)
    dx = xs[1] - xs[0]
    return ndimage.gaussian_filter(h, smooth_mm / dx)


# --- terraces -------------------------------------------------------------------------------

def _filled(xs, ys, h, lo) -> shapely.Geometry:
    """Region where h >= lo, as shapely polygons."""
    gen = contourpy.contour_generator(xs, ys, h, fill_type=contourpy.FillType.OuterOffset)
    pts_list, off_list = gen.filled(lo, np.inf)
    polys = []
    for pts, offs in zip(pts_list, off_list):
        rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
        if len(rings[0]) >= 4:
            polys.append(shapely.Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4]))
    return shapely.make_valid(shapely.unary_union(polys)) if polys else shapely.Polygon()


def _clean(g: shapely.Geometry, min_feature: float, min_area: float = 2.0) -> shapely.Geometry:
    r = min_feature / 2
    g = g.buffer(-r, quad_segs=8).buffer(r, quad_segs=8)  # drop slivers and tiny islands
    g = g.buffer(r, quad_segs=8).buffer(-r, quad_segs=8)  # close narrow gaps
    g = g.simplify(0.04)
    parts = [p for p in getattr(g, "geoms", [g]) if p.area >= min_area and p.geom_type == "Polygon"]
    return shapely.MultiPolygon(parts) if parts else shapely.Polygon()


def terraces(source: str, region: shapely.Polygon, n_levels: int, min_feature: float,
             res: float = 0.2, q_lo: float = 0.12, q_hi: float = 0.985) -> list[shapely.Geometry]:
    """Nested terrace polygons (lowest first), clipped to `region`.

    Levels are evenly spaced in elevation between the q_lo and q_hi quantiles of
    the terrain inside the region; every band is kept at least `min_feature` wide.
    """
    # Work on an enlarged area and clip at the end, so the plate outline doesn't
    # distort the map (no artificial stepped frame along the rim).
    big = region.buffer(4.0)
    x0, y0, x1, y1 = big.bounds
    xs = np.arange(x0 - 1, x1 + 1, res)
    ys = np.arange(y0 - 1, y1 + 1, res)
    h = heightmap(source, xs, ys)
    X, Y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(region, X, Y)
    lo, hi = np.quantile(h[inside], [q_lo, q_hi])
    levels = np.linspace(lo, hi, n_levels + 1)[:-1] + (hi - lo) / (n_levels + 1) * 0.5
    nested, prev = [], big
    for t in levels:
        g = _clean(_filled(xs, ys, h, t).intersection(prev), min_feature)
        if g.is_empty:
            break
        nested.append(g)
        prev = g.buffer(-min_feature, quad_segs=8)  # next band stays >= min_feature wide
    out, prev = [], region
    for g in nested:
        # Strictly nested: every terrace sits on the one below (no floating overhangs).
        g = _open(_clean(g.intersection(region), min_feature).intersection(prev), min_feature)
        if g.is_empty:
            break
        out.append(g)
        prev = g
    return out


def _open(g: shapely.Geometry, min_feature: float, min_area: float = 2.0) -> shapely.Geometry:
    """Morphological opening only (never grows the shape, so nesting is preserved)."""
    r = min_feature / 2
    g = g.buffer(-r, quad_segs=6).buffer(r - 1e-3, quad_segs=6).simplify(0.04)
    parts = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area >= min_area]
    return shapely.MultiPolygon(parts) if parts else shapely.Polygon()


def save_preview(levels: list[shapely.Geometry], region: shapely.Polygon, path: str, extra=()) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from shapely.plotting import plot_polygon

    fig, ax = plt.subplots(figsize=(4, 8))
    plot_polygon(region, ax=ax, add_points=False, color="#ddd", alpha=1)
    cmap = plt.get_cmap("terrain")
    for i, g in enumerate(levels):
        if not g.is_empty:
            plot_polygon(g, ax=ax, add_points=False, color=cmap(0.25 + 0.6 * i / max(1, len(levels) - 1)), alpha=1, linewidth=0.3)
    for g in extra:
        plot_polygon(g, ax=ax, add_points=False, facecolor="none", edgecolor="k", linewidth=0.6)
    ax.set_aspect("equal"); ax.invert_xaxis()  # view from the back
    ax.set_title("relief seen from the back")
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
