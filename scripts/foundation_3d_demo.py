"""IFC guardado → voxeles → solver 3D: enfriamiento SINTÉTICO, no predicción.

Convección en caras expuestas, base adiabática. No hay hidratación ni suelo
modelado. La geometría viene de IfcOpenShell y el material del enlace IFC/1D.
"""

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.voxelize_foundation import case_ifc
from thermal1d.case import apply_override, load_case
from thermal1d.solver import Neumann, Robin
from thermal3d import Parameters, prepare, solve
from thermal3d.solver import effective_h
from thermal3d.voxel import load_ifc_meshes, voxelize

DEFAULTS = {"dx_m": 0.25, "dz_m": 0.275, "initial_c": 30.0, "air_c": 10.0,
            "h_w_m2k": 10.0, "insulation_resistance_m2k_w": 0.0, "duration_s": 7*86400.0}


def run(config_path, output, ifc_path=None, overrides=()):
    """Ejecuta con máscaras IFC, preservando JSON, IFC y resultados 1D."""
    options = dict(DEFAULTS)
    for assignment in overrides:
        options = apply_override(options, assignment)
    if set(options) != set(DEFAULTS):
        raise ValueError("Parámetro de demostración desconocido")
    path, guids = case_ifc(config_path, ifc_path)
    case = load_case(config_path, ifc_path=path)
    meshes, source = load_ifc_meshes(path, guids)
    grid = voxelize(meshes, (options["dx_m"], options["dx_m"], options["dz_m"]), source)
    thermal = case.config["thermal"]
    h = effective_h(options["h_w_m2k"], options["insulation_resistance_m2k_w"])
    air = Robin(h, options["air_c"])
    p = Parameters(grid.component.shape, tuple(grid.lengths_m), thermal["conductivity_w_mk"],
                   thermal["density_kg_m3"], thermal["specific_heat_j_kgk"], 1e-8, options["duration_s"],
                   {"x-": air, "x+": air, "y-": air, "y+": air, "z-": Neumann(), "z+": air},
                   active=grid.active, exposed=air)
    coefficients = prepare(p)
    p = replace(p, dt_s=0.8*min(coefficients.general_dt_s, coefficients.local_dt_s))
    steps = math.ceil(p.duration_s/p.dt_s)
    result = solve(p, np.full(p.shape, options["initial_c"]), save_every=max(1, math.ceil(steps/28)))
    i, j = p.shape[0]//2, p.shape[1]//2
    if not p.active[i, j].any():
        raise ValueError("El eje central de la caja no cruza el sólido; use otra sonda para este IFC")
    active_z = np.flatnonzero(p.active[i, j])
    center = int(active_z[len(active_z)//2])
    report = {"data_status": "Demostración SINTÉTICA: sin hidratación, clima real ni suelo. No es predicción G8.",
              "options": options, "effective_h_w_m2k": h, "voxel": grid.report,
              "material": {"conductivity_w_mk": p.conductivity_w_mk, "density_kg_m3": p.density_kg_m3,
                           "specific_heat_j_kgk": p.specific_heat_j_kgk},
              "dt_s": p.dt_s, "steps": steps, "saved_states": len(result.time_s),
              "final_time_s": float(result.time_s[-1]), "final_center_temperature_c": float(result.temperature_c[-1, i, j, center]),
              "probe_index": [i, j, center],
              "probe_global_m": (grid.origin_m + (np.asarray([i, j, center])+0.5)*grid.spacing_m).tolist(),
              "max_energy_balance_relative_error": float(np.max(np.abs(result.energy_balance_error_j))/result.energy_j[0]),
              "boundary_heat_in_j": float(result.boundary_heat_in_j[-1]),
              "source_heat_in_j": float(result.source_heat_in_j[-1]),
              "energy_change_j": float(result.energy_j[-1]-result.energy_j[0])}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/"demo_termica_fundacion.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    np.savez_compressed(output/"temperatura_final.npz", temperature_c=result.temperature_c[-1],
                        component=grid.component, origin_m=grid.origin_m, spacing_m=grid.spacing_m,
                        ifc_sha256=source["sha256"], time_s=result.time_s[-1])
    fig, (section, history) = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    image = np.where(p.active[:, j, :], result.temperature_c[-1, :, j, :], np.nan)
    im = section.imshow(image.T, origin="lower", aspect="auto", extent=[0, p.lengths_m[0], 0, p.lengths_m[2]], cmap="inferno")
    fig.colorbar(im, ax=section, label="T [°C]")
    section.set(xlabel="x local [m]", ylabel="z local [m]", title="Enfriamiento sintético sobre IFC voxelizado")
    history.plot(result.time_s/86400, result.temperature_c[:, i, j, center], label="Sonda central activa")
    history.set(xlabel="Tiempo [días]", ylabel="T [°C]", title="Sin hidratación ni clima real")
    history.grid(alpha=0.3)
    history.legend()
    fig.savefig(output/"demo_termica_fundacion.png", dpi=150)
    plt.close(fig)
    print(report["data_status"])
    print(f"IFC {source['file']}: {grid.report['active_cells']} voxeles activos; {steps} pasos; T central final={report['final_center_temperature_c']:.6f} °C")
    print(f"Error relativo del balance={report['max_energy_balance_relative_error']:.6e}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--ifc", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/voxel"))
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    args = parser.parse_args()
    run(args.config, args.output, args.ifc, args.overrides)
