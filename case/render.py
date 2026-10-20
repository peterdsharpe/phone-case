"""Preview renders (pyvista, software OpenGL so the GPU and display are never touched)."""

from __future__ import annotations

import os

# Headless Mesa llvmpipe through EGL; must be set before VTK loads.
os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkEGLRenderWindow")
os.environ.setdefault("__EGL_VENDOR_LIBRARY_FILENAMES", "/usr/share/glvnd/egl_vendor.d/50_mesa.json")
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
os.environ.setdefault("EGL_PLATFORM", "surfaceless")

import numpy as np  # noqa: E402
import pyvista as pv  # noqa: E402

COLORS = {
    "hazel": "#8c9586",
    "screen": "#0b0c0e",
    "bar": "#7d857a",
    "lens": "#050506",
    "tpu": "#3b3e44",
    "galaxy": "#2a2d3a",
    "clear": "#dfe9ee",
    "white": "#eeeeea",
    "bed": "#3a3a3a",
}


def mesh(shape, tol: float = 0.03) -> pv.PolyData:
    if hasattr(shape, "faces") and hasattr(shape, "vertices") and not callable(shape.faces):  # a trimesh
        return pv.wrap(shape)
    verts, tris = shape.tessellate(tol, 0.2)
    v = np.array([(p.X, p.Y, p.Z) for p in verts], dtype=float)
    f = np.hstack([np.full((len(tris), 1), 3), np.array(tris)]).ravel()
    return pv.PolyData(v, f).clean()


def plotter(size=(1600, 1200)) -> pv.Plotter:
    pl = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    pl.set_background("white", top="#d9dee5")
    pl.add_light(pv.Light(light_type="camera light", position=(-0.6, 0.8, 1.0), intensity=0.9))  # key
    pl.add_light(pv.Light(light_type="camera light", position=(0.9, 0.2, 0.6), intensity=0.45))  # fill
    pl.add_light(pv.Light(light_type="camera light", position=(0.0, -0.4, -1.0), intensity=0.5))  # rim
    pl.enable_anti_aliasing("ssaa")
    return pl


def add(pl, m: pv.PolyData, color: str, opacity: float = 1.0, specular: float = 0.25, **kw):
    kw.setdefault("ambient", 0.22)
    pl.add_mesh(m, color=color, opacity=opacity, smooth_shading=True, split_sharp_edges=True,
                specular=specular, specular_power=25, **kw)


def shoot(pl, path: str, camera_position, zoom: float = 1.0, parallel: bool = False, fit: bool = True):
    """Look along camera_position's direction, fit everything in view, then zoom."""
    pl.camera_position = camera_position
    pl.camera.view_angle = 16  # long lens: less keystoning
    if parallel:
        pl.enable_parallel_projection()
    if fit:
        pl.reset_camera()
    pl.camera.zoom(zoom)
    img = pl.screenshot(None, return_img=True)
    pl.close()
    from PIL import Image

    # JPEG for the renders (a fifth of the size of PNG); full chroma keeps thin coloured beads crisp
    Image.fromarray(img).save(path, **(dict(quality=90, subsampling=0) if path.endswith(".jpg") else {}))
