"""Ejecuta el caso de verificación y exporta datos y figuras."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal1d.solver import Parameters, sine_reference, solve


def run(config_path: Path, output: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    p = Parameters(**config["thermal"])
    amplitude = config["verification"]["amplitude_c"]
    x = np.linspace(0, p.length_m, p.nodes)
    solution = solve(p, sine_reference(p, x, 0, amplitude))
    exact = sine_reference(p, x[None, :], solution.time_s[:, None], amplitude)
    error = solution.temperature_c - exact
    output.mkdir(parents=True, exist_ok=True)

    snapshots = np.unique(np.linspace(0, len(solution.time_s) - 1, 5, dtype=int))
    with (output / "profiles.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "z_m", "temperature_c", "exact_c", "error_c"])
        for step in snapshots:
            writer.writerows(zip(np.full(p.nodes, solution.time_s[step]), x,
                                 solution.temperature_c[step], exact[step], error[step]))

    indices = [0, p.nodes // 4, p.nodes // 2, p.nodes - 1]
    with (output / "history.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s"] + [f"T_at_z_{x[i]:.4f}_m_c" for i in indices])
        writer.writerows(np.column_stack([solution.time_s, solution.temperature_c[:, indices]]))

    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for step in snapshots:
        line, = ax.plot(x, solution.temperature_c[step], label=f"{solution.time_s[step]/86400:g} días")
        ax.plot(x, exact[step], "--", color=line.get_color(), linewidth=1)
    ax.set(xlabel="Altura z [m]", ylabel="Temperatura [°C]",
           title="Verificación 1D: datos sintéticos, sin hidratación")
    ax.text(.02, .03, "Línea continua: solver · Discontinua: solución exacta", transform=ax.transAxes, fontsize=9)
    ax.legend(title="Tiempo"); ax.grid(alpha=.25)
    fig.savefig(output / "profiles.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for i in indices:
        ax.plot(solution.time_s / 86400, solution.temperature_c[:, i], label=f"z = {x[i]:.3f} m")
    ax.set(xlabel="Tiempo [días]", ylabel="Temperatura [°C]",
           title="Evolución térmica del ejemplo sintético")
    ax.legend(); ax.grid(alpha=.25)
    fig.savefig(output / "history.png", dpi=160); plt.close(fig)

    summary = {
        "case": "Verificación sintética de difusión pura 1D",
        "site": config["site"], "parameters": config["thermal"],
        "assumptions": config["verification"],
        "alpha_m2_s": p.alpha_m2_s, "dx_m": p.dx_m, "fourier": p.fourier,
        "steps": len(solution.time_s) - 1,
        "final_time_s": float(solution.time_s[-1]),
        "max_abs_error_all_times_c": float(np.max(np.abs(error))),
        "final_max_abs_error_c": float(np.max(np.abs(error[-1]))),
        "final_rmse_c": float(np.sqrt(np.mean(error[-1]**2))),
        "final_center_temperature_c": float(solution.temperature_c[-1, p.nodes // 2]),
        "note": "No evalúa cumplimiento térmico de una fundación real ni reproduce el paper"
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Fo={p.fourier:.6f}; error máximo final={summary['final_max_abs_error_c']:.6g} °C")
    print(f"Resultados guardados en {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--output", type=Path, default=Path("results/example_1d"))
    args = parser.parse_args()
    run(args.config, args.output)
