"""Verificación sintética 2D/3D de G05: python -m scripts.verify_3d.

Exporta métricas reales, convergencia y figura; no lee ni modifica el caso 1D.
La figura usa n=L/Δ como abscisa: el segundo orden tiene pendiente -2.
"""

import csv
import json
from pathlib import Path
from time import perf_counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal3d.verification import acceptance, peak_memory_mb, run_battery


def main():
    """Ejecuta toda la batería y falla si algún criterio numérico no se cumple."""
    start = perf_counter()
    output = Path(__file__).resolve().parents[1] / "results" / "verification_3d"
    output.mkdir(parents=True, exist_ok=True)
    report = run_battery()
    report["checks"] = acceptance(report)
    rows = report["convergence_2d"]["rows"] + report["convergence_3d"]["rows"]
    with (output / "convergencia.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) + ["observed_order"])
        writer.writeheader()
        for dim in (2, 3):
            group = report[f"convergence_{dim}d"]
            for index, row in enumerate(group["rows"]):
                writer.writerow({**row, "observed_order": "" if index == 0 else group["orders"][index-1]})
    fig, ax = plt.subplots(figsize=(7, 5), layout="constrained")
    for dim in (2, 3):
        group = report[f"convergence_{dim}d"]
        ax.loglog([r["n"] for r in group["rows"]], [r["max_error_c"] for r in group["rows"]],
                  "o-", label=f"{dim}D, Fo por eje = 0.01")
    counts = np.array([10.0, 20.0, 40.0])
    scale = report["convergence_3d"]["rows"][0]["max_error_c"]
    ax.loglog(counts, scale * (counts / counts[0])**-2, "k--", label="Referencia: pendiente −2")
    ax.set(xlabel="Celdas por eje n = L/Δ [−]", ylabel="Error máximo [°C]",
           title="Verificación sintética: volúmenes finitos centrados")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.savefig(output / "convergencia.png", dpi=160)
    plt.close(fig)
    report["script_elapsed_s"] = perf_counter() - start
    report["peak_process_memory_mb"] = peak_memory_mb()
    report["script_under_120_s"] = report["script_elapsed_s"] < 120
    (output / "resumen.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["data_status"])
    for dim in (2, 3):
        group = report[f"convergence_{dim}d"]
        print(f"{dim}D: errores = " + ", ".join(f"{r['max_error_c']:.9e}" for r in group["rows"]))
        print(f"{dim}D: órdenes = " + ", ".join(f"{p:.9f}" for p in group["orders"]))
    print("Robin vs 1D: órdenes = " + ", ".join(f"{p:.9f}" for p in report["robin"]["orders"]))
    print(f"Comprobaciones: {sum(report['checks'].values())}/{len(report['checks'])}")
    print(f"Tiempo = {report['script_elapsed_s']:.6f} s; pico del proceso = {report['peak_process_memory_mb']:.3f} MB")
    print("Archivos: results/verification_3d/convergencia.csv, convergencia.png, resumen.json")
    if not all(report["checks"].values()) or not report["script_under_120_s"]:
        raise AssertionError(f"Criterios incumplidos: {report['checks']}")
    return report


if __name__ == "__main__":
    main()
