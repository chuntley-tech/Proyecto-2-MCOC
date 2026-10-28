"""Matriz adicional del ZIP adaptada al solver existente, sin sustituirlo.

Uso: python -m scripts.verify [--only materials exposed temporal]
     python -m scripts.verify --only exposed --set exposed.h_w_m2k=20
La batería base completa sigue en scripts.verify_3d.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.convergence_nd import study
from thermal1d.case import apply_override
from thermal3d.extra_verification import exposed, heterogeneous_energy, insulation, material_source, materials


def main(argv=None):
    """Genera matriz con resultados calculados; ningún resultado viene del ZIP."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=("materials", "exposed", "temporal"), default=["materials", "exposed", "temporal"])
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("results/verification"))
    args = parser.parse_args(argv)
    options = {"exposed": {"h_w_m2k": 10.0, "ambient_c": 0.0, "source_w_m3": 2.0}}
    for assignment in args.overrides:
        options = apply_override(options, assignment)
    if set(options) != {"exposed"} or set(options["exposed"]) != {"h_w_m2k", "ambient_c", "source_w_m3"}:
        raise ValueError("Parámetro desconocido; use exposed.h_w_m2k, ambient_c o source_w_m3")
    report = {"data_status": "Todos los parámetros son sintéticos de verificación; no mediciones G8."}
    rows = []
    if "materials" in args.only:
        report["materials"], report["heterogeneous_energy"] = materials(), heterogeneous_energy()
        report["material_source"], report["insulation"] = material_source(), insulation()
        m = report["materials"]
        # Umbrales calibrados y ejercitados en tests/test_thermal3d_extensions.py.
        ok = (m["max_steady_error_c"] == 0 and abs(m["interface_conductance_w_k"]-m["expected_conductance_w_k"]) < 5e-15
              and report["heterogeneous_energy"]["relative_energy_error"] < 1.3e-15
              and report["material_source"]["max_relative_cell_error"] < 7e-16)
        rows.append({"test": "Dos materiales y capacidades variables", "metric": m["max_steady_error_c"], "unit": "°C", "passed": ok})
    if "exposed" in args.only:
        report["exposed"] = exposed(**options["exposed"])
        e = report["exposed"]
        rows.append({"test": "Superficies expuestas y balance completo", "metric": e["max_energy_balance_relative_error"],
                     "unit": "relativo", "passed": e["max_energy_balance_relative_error"] < 7e-16 and e["inactive_max_change_c"] == 0})
    if "temporal" in args.only:
        report["temporal"] = study()["temporal"]
        for dim, group in report["temporal"].items():
            rows.append({"test": f"Orden temporal {dim}", "metric": min(group["orders"]), "unit": "orden",
                         "passed": all(0.985 < order < 1.015 for order in group["orders"])})
    # Normaliza booleanos numpy antes de serializar.
    rows = [{**row, "passed": bool(row["passed"])} for row in rows]
    report["matrix"] = rows
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"resultados.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    with (args.output/"matriz.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = "| Test | Métrica | Unidad | Resultado |\n|---|---:|---|---|\n"
    table += "".join(f"| {r['test']} | {r['metric']:.9e} | {r['unit']} | {'OK' if r['passed'] else 'FALLA'} |\n" for r in rows)
    (args.output/"matriz.md").write_text(table, encoding="utf-8")
    if "exposed" in report:
        e = report["exposed"]
        energy_change = np.asarray(e["energy_j"])-e["energy_j"][0]
        net_heat = np.asarray(e["boundary_history_j"])+np.asarray(e["source_history_j"])
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
        axes[0].plot(e["time_s"], energy_change, label="E − E inicial")
        axes[0].plot(e["time_s"], net_heat, "--", label="Calor neto entrante")
        axes[0].set(xlabel="Tiempo [s]", ylabel="Energía [J]", title="Balance sintético: superficies y fuente")
        axes[0].legend()
        axes[1].plot(e["time_s"], energy_change-net_heat)
        axes[1].set(xlabel="Tiempo [s]", ylabel="Residuo [J]", title="Error de balance calculado")
        fig.savefig(args.output/"energia.png", dpi=150)
        plt.close(fig)
    if "materials" in report:
        m = report["materials"]
        fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
        ax.plot(m["centers_m"], m["exact_profile_c"], label="Exacta: resistencias en serie")
        ax.plot(m["centers_m"], m["calculated_profile_c"], "o", fillstyle="none", label="Solver")
        ax.set(xlabel="y [m]", ylabel="T [°C]", title="Dos materiales sintéticos, estado estacionario")
        ax.legend()
        fig.savefig(args.output/"perfiles_materiales.png", dpi=150)
        plt.close(fig)
    print(table)
    if not all(row["passed"] for row in rows):
        raise AssertionError("No pasó toda la matriz adicional")
    return report


if __name__ == "__main__":
    main()
