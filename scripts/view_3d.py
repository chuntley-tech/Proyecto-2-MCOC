"""Abre los resultados 3D de scripts.weather_3d: slices, clipping, núcleo y superficie.

    python -m scripts.view_3d results/weather_3d/<snapshot>            # último cuadro, imágenes PNG
    python -m scripts.view_3d results/weather_3d/<snapshot> --frame 4
    python -m scripts.view_3d results/weather_3d/<snapshot> --show     # ventana interactiva PyVista

Siempre genera cortes con Matplotlib. --show abre una vista interactiva con
clipping y cortes ortogonales si PyVista está instalado.
En ParaView: File > Open > temperature.pvd.
"""

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal3d.vtk_export import read_vti


def frame_path(folder, frame):
    if frame == -1 and (folder / "final.vti").is_file():
        return folder / "final.vti"
    collection = folder / "temperature.pvd"
    if collection.is_file():
        entries = ElementTree.parse(collection).findall("./Collection/DataSet")
        if not -len(entries) <= frame < len(entries):
            raise ValueError(f"Cuadro {frame} fuera de la serie de {len(entries)} estados")
        file = folder / entries[frame].attrib["file"]
        if file.is_file():
            return file
    raise FileNotFoundError(f"No hay .vti en {folder}; ejecute primero scripts.weather_3d")


def matplotlib_slices(vti, summary, out):
    data = read_vti(vti)
    temperature = data["cells"]["temperature"]
    zone = data["cells"]["zone"]
    origin, spacing = np.array(data["origin"]), np.array(data["spacing"])
    i, j, k = summary["core"]["cell"]
    nx, ny, nz = data["shape"]
    x = origin[0] + (np.arange(nx + 1)) * spacing[0]
    y = origin[1] + (np.arange(ny + 1)) * spacing[1]
    z = origin[2] + (np.arange(nz + 1)) * spacing[2]
    finite = temperature[np.isfinite(temperature)]
    limits = dict(vmin=float(finite.min()), vmax=float(finite.max()), cmap="inferno")
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), layout="constrained",
                             gridspec_kw={"width_ratios": [1, 1, 1]})
    sections = (("vertical XZ por el núcleo (y = %.2f m)", temperature[:, j, :].T, zone[:, j, :].T, x, z, "x [m]", "z [m]"),
                ("vertical YZ por el núcleo (x = %.2f m)", temperature[i, :, :].T, zone[i, :, :].T, y, z, "y [m]", "z [m]"),
                ("horizontal XY por el núcleo (z = %.2f m)", temperature[:, :, k].T, zone[:, :, k].T, x, y, "x [m]", "y [m]"))
    centre = summary["core"]["xyz_m"]
    for ax, (title, field, zones, h, v, xl, yl), at in zip(axes, sections, (centre[1], centre[0], centre[2])):
        image = ax.pcolormesh(h, v, np.ma.masked_invalid(field), shading="flat", **limits)
        ax.contour((h[:-1] + h[1:]) / 2, (v[:-1] + v[1:]) / 2, (zones == 2).astype(float), levels=[0.5],
                   colors="cyan", linewidths=0.8)
        ax.set(title=title % at, xlabel=xl, ylabel=yl, aspect="equal")
    core = summary["core"]["xyz_m"]
    axes[0].plot(core[0], core[2], "w*", ms=14, mec="k", label="núcleo")
    axes[1].plot(core[1], core[2], "w*", ms=14, mec="k")
    axes[2].plot(core[0], core[1], "w*", ms=14, mec="k")
    for name, marker in (("superior", "o"), ("lateral", "s")):
        p = summary["surface_probes"][name]["xyz_m"]
        axes[0].plot(p[0], p[2], marker, color="lime", mec="k", ms=8, label=f"superficie {name}")
    axes[0].legend(fontsize=8, loc="lower left")
    fig.colorbar(image, ax=axes, label="temperatura [°C]", shrink=0.8)
    t = data["fields"].get("TimeValue", float("nan"))
    fig.suptitle(f"t = {t:g} h · contorno cian = superficie expuesta al aire · {summary['weather'].get('folder') or 'SINTÉTICO'}")
    fig.savefig(out, dpi=130)
    plt.close(fig)


def pyvista_view(vti, summary):
    import pyvista as pv

    mesh = pv.read(str(vti))
    concrete = mesh.threshold(value=(0.5, 1.5), scalars="material", preference="cell")
    soil = mesh.threshold(value=(1.5, 2.5), scalars="material", preference="cell")
    core = np.array(summary["core"]["xyz_m"])
    plotter = pv.Plotter(window_size=(1600, 1000), shape=(1, 2))
    # Izquierda: clipping por el plano y = núcleo (se ve el interior) + suelo semitransparente.
    plotter.subplot(0, 0)
    plotter.add_text("Clipping por y = núcleo", font_size=10)
    plotter.add_mesh(concrete.clip(normal="y", origin=core, invert=False), scalars="temperature", cmap="inferno",
                     show_edges=False, scalar_bar_args={"title": "T [°C]"})
    plotter.add_mesh(soil.clip(normal="y", origin=core, invert=False), color="saddlebrown", opacity=0.25)
    # Derecha: slices ortogonales por el núcleo.
    plotter.subplot(0, 1)
    plotter.add_text("Slices ortogonales por el núcleo", font_size=10)
    plotter.add_mesh(concrete.slice_orthogonal(x=core[0], y=core[1], z=core[2]), scalars="temperature",
                     cmap="inferno", show_scalar_bar=False)
    plotter.add_mesh(concrete.extract_surface(), style="wireframe", color="gray", opacity=0.15)
    for column in (0, 1):
        plotter.subplot(0, column)
        plotter.add_points(core[None, :], color="white", point_size=18, render_points_as_spheres=True)
        plotter.add_point_labels(core[None, :], ["núcleo"], font_size=14, text_color="white", shape_opacity=0.4)
        for name, colour in (("superior", "lime"), ("lateral", "cyan")):
            point = np.array(summary["surface_probes"][name]["xyz_m"])[None, :]
            plotter.add_points(point, color=colour, point_size=14, render_points_as_spheres=True)
            plotter.add_point_labels(point, [f"superficie {name}"], font_size=12, shape_opacity=0.4)
        plotter.camera_position = "iso"
    plotter.link_views()
    plotter.show()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--frame", type=int, default=-1)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)
    folder = Path(args.folder)
    summary = json.loads((folder / "resumen.json").read_text(encoding="utf-8"))
    vti = frame_path(folder, args.frame)
    out = folder / f"slices_{vti.stem}.png"
    matplotlib_slices(vti, summary, out)
    print(f"Slices (Matplotlib): {out}")
    if not args.show:
        return
    try:
        import pyvista  # noqa: F401
    except ImportError:
        print("PyVista no está instalado: abra temperature.pvd en ParaView, o instale con  pip install pyvista")
        return
    pyvista_view(vti, summary)


if __name__ == "__main__":
    main()
