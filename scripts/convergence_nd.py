"""Estudio temporal 2D/3D adaptado del ZIP; API centrada existente, G05.

Compara Euler contra el seno semidiscreto, separando el error temporal del
espacial. Todos los parámetros son sintéticos. No modifica resultados 1D.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal1d.solver import Dirichlet
from thermal3d import Parameters, solve
from thermal3d.reference import sine_exact, sine_initial


def study():
    """Convergencia temporal a grilla fija contra integración espacial exacta."""
    groups = {}
    for dim in (2, 3):
        rows = []
        for steps in (40, 80, 160, 320):
            p = Parameters((12,)*dim, (1.0,)*dim, 1.0, 1.0, 1.0, 0.02/steps, 0.02,
                           {f: Dirichlet(0.0) for f in ("x-", "x+", "y-", "y+", "z-", "z+")[:2*dim]})
            result = solve(p, sine_initial(p), save_every=10**9)
            exact = sine_exact(p, p.duration_s, semidiscrete=True)
            rows.append({"dimension": dim, "n": 12, "steps": steps, "dt_s": p.dt_s,
                         "temporal_error_c": float(np.max(np.abs(result.temperature_c[-1]-exact))),
                         "total_error_c": float(np.max(np.abs(result.temperature_c[-1]-sine_exact(p, p.duration_s))))})
        errors = np.array([r["temporal_error_c"] for r in rows])
        orders = np.log2(errors[:-1]/errors[1:])
        groups[f"{dim}D"] = {"rows": rows, "orders": orders.tolist()}
    return {"data_status": "Verificación sintética; no datos de mezcla ni clima G8", "temporal": groups}


def run(output):
    """Exporta estudio y falla si no se observa el orden temporal de Euler."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = study()
    rows = report["temporal"]["2D"]["rows"] + report["temporal"]["3D"]["rows"]
    with (output/"temporal.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    fig, ax = plt.subplots(figsize=(7, 4.5), layout="constrained")
    for dim, group in report["temporal"].items():
        dt = np.array([r["dt_s"] for r in group["rows"]])
        error = np.array([r["temporal_error_c"] for r in group["rows"]])
        ax.loglog(dt, error, "o-", label=dim)
        print(dim+": órdenes temporales = "+", ".join(f"{v:.6f}" for v in group["orders"]))
        if not np.all((np.array(group["orders"]) > 0.985) & (np.array(group["orders"]) < 1.015)):
            raise AssertionError("No se verifica el orden temporal de Euler")
    ax.loglog(dt, error[0]*dt/dt[0], "k--", label="Referencia: pendiente 1")
    ax.set(xlabel="Δt [s]", ylabel="Error vs solución semidiscreta [°C]", title="Convergencia temporal sintética")
    ax.grid(which="both", alpha=0.3)
    ax.legend()
    fig.savefig(output/"temporal.png", dpi=150)
    plt.close(fig)
    (output/"resumen.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/convergence_nd"))
    run(parser.parse_args().output)
