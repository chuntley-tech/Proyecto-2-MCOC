"""Ejecuta un caso térmico 1D definido en JSON y exporta datos y figuras.

Uso (desde la raíz del repositorio):
    python -m scripts.run_case
    python -m scripts.run_case --config config/ejemplos/04_robin_video.json --output results/ejemplos/04_robin_video
    python -m scripts.run_case --config config/ejemplos/plantilla_hormigon.json --set top.h_w_m2k=20
    python -m scripts.run_case --set thermal.dt_s=1300 --allow-unstable     # demostración de inestabilidad

Cada `--set ruta=valor` cambia un dato del JSON sin editar el archivo.
"""

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from thermal1d.case import load_case
from thermal1d.reference import sine_reference
from thermal1d.solver import energy_per_area_j_m2, solve

MAX_SAVED_STEPS = 5000


def _time_unit(duration_s):
    if duration_s >= 4 * 86400:
        return 86400.0, "días"
    if duration_s >= 3 * 3600:
        return 3600.0, "h"
    return 60.0, "min"


def describe_boundary(spec):
    kind = spec["type"].lower()
    if kind == "dirichlet":
        return f"Dirichlet: T = {spec['temperature_c']:g} °C"
    if kind == "neumann":
        flux = spec.get("flux_in_w_m2", 0.0)
        return "Neumann: adiabático" if flux == 0 else f"Neumann: entra {flux:g} W/m²"
    ambient = spec["ambient_c"]
    if isinstance(ambient, dict):
        ambient_text = (f"{ambient['mean_c']:g} ± {ambient.get('amplitude_c', 0):g} °C, "
                        f"período {ambient['period_h']:g} h")
    else:
        ambient_text = f"{ambient:g} °C"
    return f"Robin: h = {spec['h_w_m2k']:g} W/m²K, aire {ambient_text}"


def run(config_path: Path, output: Path, overrides=()):
    case = load_case(config_path, overrides)
    p = case.params
    steps = math.ceil(p.duration_s / p.dt_s)
    unstable = p.fourier > p.max_fourier + 1e-12
    with np.errstate(over="ignore", invalid="ignore"):
        solution = solve(p, case.initial_c, save_every=max(1, math.ceil(steps / MAX_SAVED_STEPS)))
    x, times, temperature = solution.x_m, solution.time_s, solution.temperature_c

    verification = case.config.get("verification")
    exact = error = None
    if verification:
        if verification.get("type") != "sine":
            raise ValueError("Solo se implementa la verificación 'sine'")
        exact = sine_reference(p, x[None, :], times[:, None], float(verification["amplitude_c"]))
        error = temperature - exact

    output_settings = case.config.get("output", {})
    snapshots = np.unique(np.linspace(0, len(times) - 1, int(output_settings.get("snapshots", 5)), dtype=int))
    probes_m = output_settings.get("probes_m", [0.0, p.length_m / 4, p.length_m / 2, p.length_m])
    indices = list(dict.fromkeys(int(np.argmin(np.abs(x - z))) for z in probes_m))
    output.mkdir(parents=True, exist_ok=True)

    with (output / "profiles.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "z_m", "temperature_c"] + (["exact_c", "error_c"] if exact is not None else []))
        for step in snapshots:
            columns = [np.full(p.nodes, times[step]), x, temperature[step]]
            if exact is not None:
                columns += [exact[step], error[step]]
            writer.writerows(zip(*columns))

    with (output / "history.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s"] + [f"T_at_z_{x[i]:.4f}_m_c" for i in indices])
        writer.writerows(np.column_stack([times, temperature[:, indices]]))

    scale, unit = _time_unit(p.duration_s)
    title = case.name + (" (datos sintéticos)" if exact is not None else "")
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for step in snapshots:
        line, = ax.plot(x, temperature[step], label=f"{times[step] / scale:.3g} {unit}")
        if exact is not None:
            ax.plot(x, exact[step], "--", color=line.get_color(), linewidth=1)
    ax.set(xlabel="Posición z [m]", ylabel="Temperatura [°C]", title=title)
    if exact is not None:
        ax.text(.02, .03, "Línea continua: solver · Discontinua: solución exacta",
                transform=ax.transAxes, fontsize=9)
    ax.legend(title="Tiempo")
    ax.grid(alpha=.25)
    fig.savefig(output / "profiles.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for i in indices:
        ax.plot(times / scale, temperature[:, i], label=f"z = {x[i]:.3f} m")
    ax.set(xlabel=f"Tiempo [{unit}]", ylabel="Temperatura [°C]", title=f"Evolución: {case.name}")
    ax.legend()
    ax.grid(alpha=.25)
    fig.savefig(output / "history.png", dpi=160)
    plt.close(fig)

    center = p.nodes // 2
    peak = np.unravel_index(int(np.argmax(temperature)), temperature.shape)
    low = np.unravel_index(int(np.argmin(temperature)), temperature.shape)
    differential = temperature[:, center] - np.minimum(temperature[:, 0], temperature[:, -1])
    worst = int(np.argmax(differential))
    energy = energy_per_area_j_m2(p, temperature[[0, -1]])
    summary = {
        "case": case.config.get("case", {}),
        "parameters": case.config["thermal"],
        "initial": case.config["initial"],
        "bottom": case.config["bottom"],
        "top": case.config["top"],
        "source_w_m3": case.config.get("source_w_m3", 0.0),
        "overrides": list(overrides),
        "alpha_m2_s": p.alpha_m2_s,
        "dx_m": p.dx_m,
        "fourier": p.fourier,
        "max_stable_fourier": p.max_fourier,
        "biot_numbers": list(p.biot_numbers),
        "steps": steps,
        "final_time_s": float(times[-1]),
        "max_temperature_c": float(temperature[peak]),
        "max_temperature_at": {"z_m": float(x[peak[1]]), "time_s": float(times[peak[0]])},
        "min_temperature_c": float(temperature[low]),
        "final_center_temperature_c": float(temperature[-1, center]),
        "final_profile_at_probes_c": {f"{x[i]:.4f}": float(temperature[-1, i]) for i in indices},
        "max_center_minus_boundary_c": float(differential[worst]),
        "max_center_minus_boundary_time_s": float(times[worst]),
        "energy_change_j_m2": float(energy[1] - energy[0]),
        "unstable_step": unstable,
        "metric_scope": "Extremos y errores evaluados en los instantes guardados",
        "saved_instants": len(times),
        "data_status": case.config.get("case", {}).get("data_status", "Caso ilustrativo del ZIP; no es validación de la fundación real"),
    }
    if "site" in case.config:
        summary["site"] = case.config["site"]
    if exact is not None:
        summary.update({
            "max_abs_error_all_times_c": float(np.max(np.abs(error))),
            "final_max_abs_error_c": float(np.max(np.abs(error[-1]))),
            "final_rmse_c": float(np.sqrt(np.mean(error[-1]**2))),
            "note": "Verificación matemática: no evalúa la fundación real ni reproduce el paper",
        })
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")

    print(f"Caso: {case.name}")
    print(f"  Abajo: {describe_boundary(case.config['bottom'])}")
    print(f"  Arriba: {describe_boundary(case.config['top'])}")
    print(f"  Fo = {p.fourier:.4f} (máximo estable {p.max_fourier:.4f}); {steps} pasos de {p.dt_s:g} s")
    if unstable:
        print("  ADVERTENCIA: Fo supera el límite estable. Las oscilaciones crecen y el resultado NO es válido.")
    print(f"  T final en el centro (z = {x[center]:.3f} m): {summary['final_center_temperature_c']:.3f} °C")
    print(f"  T máxima: {summary['max_temperature_c']:.3f} °C en z = {x[peak[1]]:.3f} m, "
          f"t = {times[peak[0]] / scale:g} {unit}")
    if exact is not None:
        print(f"  Error máximo final respecto de la solución exacta: {summary['final_max_abs_error_c']:.3g} °C")
    print(f"  Resultados en {output}")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--set", dest="overrides", action="append", default=[],
                        metavar="RUTA=VALOR", help="cambia un dato del JSON, p. ej. top.h_w_m2k=20")
    parser.add_argument("--allow-unstable", action="store_true",
                        help="permite un Δt inestable para demostrar la inestabilidad")
    args = parser.parse_args(argv)
    if args.allow_unstable:
        args.overrides.append("check_stability=false")
    output = args.output
    if output is None:
        output = (Path("results/example_1d") if args.config.name == "case_g8.json"
                  else Path("results/ejemplos") / args.config.stem)
    return run(args.config, output, args.overrides)


if __name__ == "__main__":
    main()
