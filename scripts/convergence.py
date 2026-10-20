"""Estudio de convergencia espacial y temporal del solver 1D (entrega E03).

Caso: el de verificación G8 (config/case_g8.json): columna de 3,30 m con perfil
inicial 20 + 20 sen(πz/L) °C, extremos fijos a 20 °C y 14 días. Tiene solución
exacta, así que el error se puede medir directamente.

1. Espacial: se refina Δz (11 a 161 nodos) con Fo = 0,02 fijo. Así Δt también
   se achica y el error temporal queda mucho menor que el espacial.
   Se espera pendiente ≈ 2 (diferencias centrales de segundo orden).
2. Temporal: Δz fijo (41 nodos) y Fo de 1/2 a 1/32. El error se mide contra la
   solución exacta del sistema semidiscreto (mismo Δz, integración exacta en el
   tiempo), que elimina el error espacial. Se espera pendiente ≈ 1 (Euler
   explícito de primer orden).

Uso (desde la raíz):
    python -m scripts.convergence
    python -m scripts.convergence --config config/case_g8.json --output results/convergence
"""

import argparse
import csv
from dataclasses import replace
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal1d.case import load_case
from thermal1d.reference import sine_reference, sine_reference_semidiscrete
from thermal1d.solver import solve

SPATIAL_NODES = (11, 21, 41, 81, 161)
SPATIAL_FOURIER = 0.02
TEMPORAL_NODES = 41
TEMPORAL_FOURIER = (0.5, 0.25, 0.125, 0.0625, 0.03125)


def refined(base, nodes, fourier):
    """Mismo caso con otra malla; Δt se ajusta para terminar justo en la duración."""
    dz = base.length_m / (nodes - 1)
    steps = math.ceil(base.duration_s / (fourier * dz**2 / base.alpha_m2_s))
    return replace(base, nodes=nodes, dt_s=base.duration_s / steps), steps


def measure(base, amplitude_c, nodes, fourier):
    p, steps = refined(base, nodes, fourier)
    x = np.linspace(0, p.length_m, p.nodes)
    final = solve(p, sine_reference(p, x, 0, amplitude_c), save_every=steps).temperature_c[-1]
    exact = sine_reference(p, x, p.duration_s, amplitude_c)
    semidiscrete = sine_reference_semidiscrete(p, x, p.duration_s, amplitude_c)
    return {
        "nodes": nodes, "dz_m": p.dx_m, "dt_s": p.dt_s, "fourier": p.fourier, "steps": steps,
        "error_total_c": float(np.max(np.abs(final - exact))),
        "error_temporal_c": float(np.max(np.abs(final - semidiscrete))),
        "error_espacial_analitico_c": float(np.max(np.abs(semidiscrete - exact))),
    }


def fitted_slope(h, error):
    return float(np.polyfit(np.log(h), np.log(error), 1)[0])


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(config_path: Path, output: Path):
    case = load_case(config_path)
    amplitude = float(case.config["verification"]["amplitude_c"])
    spatial = [measure(case.params, amplitude, n, SPATIAL_FOURIER) for n in SPATIAL_NODES]
    temporal = [measure(case.params, amplitude, TEMPORAL_NODES, fo) for fo in TEMPORAL_FOURIER]

    dz = np.array([r["dz_m"] for r in spatial])
    e_space = np.array([r["error_total_c"] for r in spatial])
    dt = np.array([r["dt_s"] for r in temporal])
    e_time = np.array([r["error_temporal_c"] for r in temporal])
    e_total_time = np.array([r["error_total_c"] for r in temporal])
    slope_space, slope_time = fitted_slope(dz, e_space), fitted_slope(dt, e_time)

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "espacial.csv", spatial)
    write_csv(output / "temporal.csv", temporal)

    fig, ax = plt.subplots(figsize=(7, 4.8), layout="constrained")
    ax.loglog(dz, e_space, "o-", label=f"solver vs. exacta (pendiente {slope_space:.2f})")
    ax.loglog(dz, [r["error_espacial_analitico_c"] for r in spatial], "s:", markersize=4,
              label="solo error espacial (analítico)")
    ax.loglog(dz, e_space[-1] * (dz / dz[-1])**2, "k--", linewidth=1, label="referencia O(Δz²)")
    ax.set(xlabel="Δz [m]", ylabel="Error máximo a 14 días [°C]",
           title=f"Convergencia espacial (Fo = {SPATIAL_FOURIER:g} fijo)")
    ax.grid(True, which="both", alpha=.3)
    ax.legend()
    fig.savefig(output / "espacial.png", dpi=160)
    plt.close(fig)

    spatial_floor = temporal[0]["error_espacial_analitico_c"]
    fig, ax = plt.subplots(figsize=(7, 4.8), layout="constrained")
    ax.loglog(dt, e_time, "o-", label=f"solver vs. semidiscreta (pendiente {slope_time:.2f})")
    ax.loglog(dt, e_total_time, "s-", markersize=4, label="solver vs. exacta continua")
    ax.loglog(dt, e_time[-1] * dt / dt[-1], "k--", linewidth=1, label="referencia O(Δt)")
    ax.axhline(spatial_floor, color="gray", linestyle=":", label=f"error espacial con {TEMPORAL_NODES} nodos")
    ax.set(xlabel="Δt [s]", ylabel="Error máximo a 14 días [°C]",
           title=f"Convergencia temporal ({TEMPORAL_NODES} nodos, Δz = {temporal[0]['dz_m']:.4f} m)")
    ax.grid(True, which="both", alpha=.3)
    ax.legend()
    fig.savefig(output / "temporal.png", dpi=160)
    plt.close(fig)

    summary = {
        "case": case.config["case"],
        "spatial": {"nodes": list(SPATIAL_NODES), "fourier": SPATIAL_FOURIER, "slope": slope_space,
                    "expected": 2},
        "temporal": {"nodes": TEMPORAL_NODES, "fourier": list(TEMPORAL_FOURIER), "slope": slope_time,
                     "expected": 1, "spatial_error_floor_c": spatial_floor},
        "metric": "Error máximo absoluto en los nodos al final (14 días)",
        "note": "Verificación matemática con datos sintéticos; no evalúa la fundación real",
    }
    (output / "resumen.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    print(f"Convergencia espacial: pendiente {slope_space:.3f} (se espera 2)")
    print(f"Convergencia temporal: pendiente {slope_time:.3f} (se espera 1)")
    print(f"Resultados en {output}")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--output", type=Path, default=Path("results/convergence"))
    args = parser.parse_args(argv)
    return run(args.config, args.output)


if __name__ == "__main__":
    main()
