"""IFC → grilla con vertida_id → construcción térmica SINTÉTICA (G04/G05)."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.voxelize_foundation import case_ifc
from thermal1d.solver import Neumann, Robin
from thermal3d.solver import Parameters
from thermal3d.voxel import load_ifc_meshes, voxelize
from thermal3d.construction import Pour, CosineHydration, build_plan, solve_construction


def run(config_path, output):
    """Exporta procedencia IFC, grilla, cronograma, estados y balance de energía."""
    config_path, output = Path(config_path), Path(output)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    case = config_path.parent / cfg["case_config"]
    path, guids = case_ifc(case)
    meshes, source = load_ifc_meshes(path, guids)
    grid = voxelize(meshes, cfg["spacing_m"], source)
    plan = build_plan(grid, [Pour(**row) for row in cfg["pours"]])
    hydration_cfg = cfg["hydration"]
    hydration = CosineHydration(hydration_cfg["qmax_w_m3"], hydration_cfg["duration_s"])
    bc = cfg["boundary"]
    air = Robin(bc["h_w_m2k"], bc["air_c"])
    faces = {face: air for face in ("x-", "x+", "y-", "y+", "z+")}
    faces["z-"] = Neumann(bc["base_flux_in_w_m2"])
    p = Parameters(grid.component.shape, tuple(grid.lengths_m), **cfg["thermal"],
                   boundaries=faces, active=grid.active, exposed=air)
    ea = cfg.get("kinetics", {}).get("activation_energy_j_mol", 0.0)
    result = solve_construction(p, plan, hydration, save_every=24, activation_energy_j_mol=ea)
    scale = max(1.0, float(np.max(np.abs(result.energy_j))),
                float(np.max(np.abs(result.placement_energy_j))))
    report = {"data_status": cfg["data_status"], "configuration": cfg,
              "voxel": grid.report, "pours": list(plan.rows),
              "source_model": "Pulso cosenoidal SINTÉTICO por edad equivalente; q=rate(te_n)*factor(T_n)",
              "activation_energy_j_mol": ea,
              "hydration_energy_j_m3": hydration.qmax_w_m3*hydration.duration_s/2,
              "saved_times_s": result.time_s.tolist(),
              "active_cells": result.active.sum(axis=(1, 2, 3)).tolist(),
              "max_temperature_c": [float(t[a].max()) if a.any() else None
                                    for t, a in zip(result.temperature_c, result.active)],
              "energy_j": result.energy_j.tolist(),
              "boundary_heat_in_j": result.boundary_heat_in_j.tolist(),
              "source_heat_in_j": result.source_heat_in_j.tolist(),
              "placement_energy_j": result.placement_energy_j.tolist(),
              "max_balance_error_j": float(np.max(np.abs(result.energy_balance_error_j))),
              "max_balance_relative_error": float(np.max(np.abs(result.energy_balance_error_j))/scale),
              "scope": "Colocación instantánea por capa; Ea=0 conserva cinética cronológica; Ea>0 usa Arrhenius sin calibración experimental. Sin clima real ni suelo."}
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output/"construction.npz", component=grid.component,
                        vertida_id=plan.vertida_id, inicio_vertida_s=plan.start_s,
                        T_colocacion_c=plan.placement_c, origin_m=grid.origin_m,
                        spacing_m=grid.spacing_m, lengths_m=grid.lengths_m,
                        ifc_sha256=source["sha256"], time_s=result.time_s,
                        temperature_c=result.temperature_c, active=result.active,
                        equivalent_age_s=result.equivalent_age_s,
                        energy_j=result.energy_j, boundary_heat_in_j=result.boundary_heat_in_j,
                        source_heat_in_j=result.source_heat_in_j, placement_energy_j=result.placement_energy_j)
    (output/"resumen.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    axes[0].plot(result.time_s/86400, report["max_temperature_c"], "o-")
    axes[0].set(xlabel="Tiempo [días]", ylabel="Temperatura máxima activa [°C]", title="Construcción sintética por etapas")
    axes[1].step(result.time_s/86400, report["active_cells"], where="post")
    axes[1].set(xlabel="Tiempo [días]", ylabel="Celdas colocadas [−]", title="Activación del hormigón")
    fig.savefig(output/"evolucion.png", dpi=150)
    plt.close(fig)
    print(f"IFC: {source['file']} · {len(plan.rows)} vertidas · {grid.active.sum()} celdas geométricas")
    print(f"Volumen IFC: {grid.report['ifc_volume_m3']:.6f} m³; grilla: {grid.report['voxel_volume_m3']:.6f} m³")
    print(f"Residuo relativo máximo de energía: {report['max_balance_relative_error']:.6e}")
    print(f"Resultados: {output}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/construction_g8.json"))
    parser.add_argument("--output", type=Path, default=Path("results/construction"))
    args = parser.parse_args()
    run(args.config, args.output)
