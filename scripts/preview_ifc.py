"""Genera una vista de la geometría efectivamente leída desde el IFC."""

import argparse
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np


def preview(path, output):
    model = ifcopenshell.open(str(path))
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    fig = plt.figure(figsize=(12, 6), layout="constrained")
    ax = fig.add_subplot(121, projection="3d")
    section = fig.add_subplot(122)
    colors = ["#65869c", "#a5bdcb", "#e7ad65"]
    all_faces, all_colors = [], []
    elevation, azimuth = np.deg2rad([23, -55])
    view_direction = np.array([np.cos(elevation) * np.cos(azimuth),
                               np.cos(elevation) * np.sin(azimuth), np.sin(elevation)])
    for element, color in zip(sorted(model.by_type("IfcFooting"), key=lambda e: e.Tag), colors):
        shape = ifcopenshell.geom.create_shape(settings, element)
        vertices = np.asarray(shape.geometry.verts).reshape(-1, 3)
        triangles = np.asarray(shape.geometry.faces).reshape(-1, 3)
        for face in vertices[triangles]:
            # Omitir en la vista las caras internas coplanares de contacto,
            # para evitar artefactos del orden de pintado de Matplotlib.
            if any(np.all(np.abs(face[:, 2] - z) < 1e-8) for z in (1.1, 2.2)):
                continue
            normal = np.cross(face[1] - face[0], face[2] - face[0])
            if np.dot(normal, view_direction) <= 0:
                continue
            all_faces.append(face)
            all_colors.append(color)
        # Corte geométrico real en y=9 m, intersecando la triangulación IFC.
        for triangle in vertices[triangles]:
            points = []
            for p, q in zip(triangle, np.roll(triangle, -1, axis=0)):
                if (p[1] - 9) * (q[1] - 9) < 0:
                    points.append(p + (q - p) * (9 - p[1]) / (q[1] - p[1]))
                elif abs(p[1] - 9) < 1e-8:
                    points.append(p)
            if len(points) >= 2:
                section.plot([points[0][0] - 9, points[1][0] - 9],
                             [points[0][2], points[1][2]], color=color, linewidth=2)
    # Una sola colección ordena la profundidad por cara entre los tres sólidos.
    ax.add_collection3d(Poly3DCollection(all_faces, facecolor=all_colors, edgecolor="none"))
    ax.set(xlim=(0, 18), ylim=(0, 18), zlim=(0, 4), xlabel="x [m]", ylabel="y [m]", zlabel="z [m]",
           title="Geometría triangulada del IFC")
    ax.set_box_aspect((18, 18, 5))
    ax.view_init(elev=23, azim=-55)
    section.set(xlabel="Distancia al eje [m]", ylabel="Altura [m]", title="Sección central leída del IFC",
                xlim=(-9.5, 9.5), ylim=(-.2, 3.8))
    section.set_aspect("equal")
    section.grid(alpha=.25)
    fig.suptitle("G8 · Zócalo octagonal, transición aproximada y cilindro Ø7 m")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ifc", type=Path, default=Path("models/g8_base.ifc"))
    parser.add_argument("--output", type=Path, default=Path("results/foundation_preview.png"))
    args = parser.parse_args()
    preview(args.ifc, args.output)
