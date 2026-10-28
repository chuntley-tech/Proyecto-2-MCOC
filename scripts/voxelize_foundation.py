"""Voxelización del IFC real guardado y convergencia de volumen (G04).

Adaptación del estudio del ZIP: reemplaza la reconstrucción desde cotas JSON
por la triangulación directa del IFC. No presupone alturas ni cilindros.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal3d.voxel import load_ifc_meshes, voxelize


def case_ifc(config_path, override=None):
    """Resuelve ruta y selección por GUID; las cotas del JSON no se usan."""
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    binding = config["ifc"]
    path = Path(override).resolve() if override else (config_path.parent/binding["path"]).resolve()
    return path, binding.get("element_guids")


def run(config_path, output, ifc_path=None):
    """Cuatro resoluciones, referencia IFC, NPZ y figuras reproducibles."""
    path, guids = case_ifc(config_path, ifc_path)
    meshes, source = load_ifc_meshes(path, guids)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for dx in (0.5, 0.25, 0.125, 0.0625):
        grid = voxelize(meshes, (dx, dx, 1.1*dx), source)
        r = grid.report
        rows.append({"requested_dx_m": dx, "dx_m": float(grid.spacing_m[0]), "dz_m": float(grid.spacing_m[2]),
                     "active_cells": r["active_cells"], "ifc_volume_m3": r["ifc_volume_m3"],
                     "voxel_volume_m3": r["voxel_volume_m3"], "relative_volume_error": r["relative_volume_error"]})
        print(f"Δx solicitado={dx:g} m; volumen={r['voxel_volume_m3']:.6f} m³; error={r['relative_volume_error']:.6e}")
        if dx == 0.25:
            saved = grid
            np.savez_compressed(output/"fundacion_0.25m.npz", component=grid.component, spacing_m=grid.spacing_m,
                                origin_m=grid.origin_m, lengths_m=grid.lengths_m,
                                guids=np.asarray([m.guid for m in meshes]), ifc_sha256=source["sha256"])
    with (output/"volumen.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {"source": source, "rows": rows, "saved_grid": saved.report,
              "scope": "Error de volumen contra la triangulación IFC. No se presupone convergencia monótona ni se certifica error térmico."}
    (output/"resumen.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    fig, (ax, section) = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    ax.loglog([r["dx_m"] for r in rows], [r["relative_volume_error"] for r in rows], "o-")
    ax.set(xlabel="Δx [m]", ylabel="Error relativo de volumen [−]", title="Centros de voxel vs malla IFC")
    ax.grid(which="both", alpha=0.3)
    image = saved.component[:, saved.component.shape[1]//2, :].T.astype(float)
    image[image == 0] = np.nan
    section.imshow(image, origin="lower", aspect="auto", extent=[0, saved.lengths_m[0], 0, saved.lengths_m[2]])
    section.set(xlabel="x local [m]", ylabel="z local [m]", title="Componentes del IFC: corte central")
    fig.savefig(output/"voxelizacion.png", dpi=150)
    plt.close(fig)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--ifc", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/voxel"))
    args = parser.parse_args()
    run(args.config, args.output, args.ifc)
