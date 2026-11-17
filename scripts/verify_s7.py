"""Refinamiento reproducible del escenario crítico de S7, con malla y tiempo separados."""

import argparse
from pathlib import Path
import numpy as np
from scripts import final_campaign as campaign, final_mc, monte_carlo as io
from scripts.final_mc_refinement import contact, richardson

LOT = campaign.ROOT / "results/final/g8_20261119_mc/s7_base"
OUT = campaign.ROOT / "results/final/s7_convergence"
REFERENCE = OUT / "reference.json"


def inputs():
    """Lee las referencias archivadas para reproducir el ensayo sin el lote completo."""
    reference = io.read_json(REFERENCE)
    if io.digest(LOT / "manifest.json") != reference["manifest_sha256"]:
        raise ValueError("El manifiesto difiere de la referencia archivada")
    manifest = io.read_json(LOT / "manifest.json")
    sample = reference["base"]
    job = manifest["jobs"][sample["index"]]
    if any(sample[key] != value for key, value in job.items()):
        raise ValueError("La realización archivada difiere del manifiesto")
    return manifest, reference


def run(mesh, dt, weather_snapshot=None):
    """Mantiene escenario, horizonte, recursos y cronograma del lote original."""
    manifest, reference = inputs()
    if io.digest(campaign.SOURCE) != manifest["source_sha256"]:
        raise ValueError("La fuente de calor cambió respecto del lote S7")
    sample = reference["base"]
    job = {**manifest["jobs"][sample["index"]], "mesh": mesh, "dt": dt}
    config = manifest["config"]
    expected_weather = manifest["weather_sha256"]
    suffix = ""
    if weather_snapshot:
        config = {**config, "weather_snapshot": weather_snapshot}
        members, common, _ = final_mc.complete_members(config, config["hours"])
        if job["climate"]["member"] not in members:
            raise ValueError("El nuevo ensamble no cubre el miembro del escenario durante 14 días")
        config["common_forecast_hours"] = common
        expected_weather = campaign.weather_snapshot(weather_snapshot)[0]["sha256"]
        suffix = "_" + Path(weather_snapshot).name
    output = OUT / f"mesh_{mesh:g}_dt_{dt:g}{suffix}.json"
    if output.exists():
        raise FileExistsError(f"Resultado existente: {output}")
    result = campaign.simulate(job, config, manifest["environment"])
    for key, expected in (("ifc_sha256", manifest["ifc_sha256"]), ("weather_sha256", expected_weather)):
        if result[key] != expected:
            raise ValueError(f"Insumo distinto del lote S7: {key}")
    result["ifc_contact"] = contact(result["delta"]["surface"])
    payload = {"row": result, "sample_id": sample["sample_id"],
               "manifest_sha256": io.digest(LOT / "manifest.json"),
               "source_sha256": io.digest(campaign.SOURCE),
               "code_sha256": io.code_fingerprint(), "weather_snapshot": config["weather_snapshot"]}
    io.write_json(output, payload)
    print(f"Guardado {output}", flush=True)
    print(f"Tmax={result['tmax']['value_c']:.8f}; delta={result['delta']['value_c']:.8f}; "
          f"pasos={result['steps']}; tiempo={result['run_seconds']:.1f} s", flush=True)


def aggregate():
    """Compara máximos globales; Richardson queda condicionado a la secuencia observada."""
    manifest, reference = inputs()
    base = reference["base"]
    medium = reference["medium"]
    if (OUT / "mesh_1_dt_600.json").is_file():
        medium = io.read_json(OUT / "mesh_1_dt_600.json")["row"]
    coarse600 = io.read_json(OUT / "mesh_2_dt_600.json")["row"]
    fine_path = OUT / "mesh_0.5_dt_600.json"
    fine = io.read_json(fine_path)["row"] if fine_path.is_file() else None
    coarse300 = io.read_json(OUT / "mesh_2_dt_300.json")["row"]
    studies = {}
    for name, rows in (("spatial", [coarse600, medium] + ([fine] if fine else [])),
                       ("temporal", [base, coarse600, coarse300])):
        for row in rows:
            for key in ("plan", "sample_id", "curve", "climate", "heat_factor", "soil_c",
                        "placement_c", "ifc_sha256", "weather_sha256", "hours"):
                if row[key] != base[key]:
                    raise ValueError(f"Escenario distinto en {name}: {key}")
        spacing = np.array([row["grid_spacing_m"] for row in rows])
        steps = np.array([row["dt"] for row in rows])
        if name == "spatial":
            valid = np.all(steps == steps[0]) and np.all(np.diff(spacing, axis=0) < 0)
        else:
            valid = np.allclose(spacing, spacing[0]) and np.allclose(steps[:-1], 2*steps[1:])
        if not valid:
            raise ValueError(f"Refinamiento incompatible con el estudio {name}")
        estimates = {}
        for metric in ("tmax", "delta"):
            values = [row[metric]["value_c"] for row in rows]
            estimate = richardson(values) if len(values) == 3 else {
                "order": None, "extrapolated_c": None, "reason": "Falta el tercer nivel"}
            if name == "spatial" and estimate["order"] is not None and not np.allclose(spacing[:-1], 2*spacing[1:]):
                estimate = {"order": None, "extrapolated_c": None,
                            "reason": "El ajuste al IFC cambia la razón de refinamiento en z"}
            estimates[metric] = {**estimate, "last_change_c": values[-1]-values[-2],
                                 "last_change_relative": abs(values[-1]-values[-2])/abs(values[-1])}
        studies[name] = {"rows": rows, "estimates": estimates,
                        "all_horizons_closed": all(not row["horizon_open"] for row in rows)}
    evidence = io.read_json(LOT / "convergence.json")
    evidence.update(studies=studies, kind="separate_spatial_temporal",
                    fine_delta_c=fine["delta"]["value_c"] if fine else None,
                    fine_margin_delta_c=20-fine["delta"]["value_c"] if fine else None,
                    source_sha256=manifest["source_sha256"])
    io.write_json(OUT / "summary.json", evidence)
    plot(evidence)
    print({key: study["estimates"] for key, study in studies.items()}, flush=True)


def plot(evidence):
    """Grafica magnitudes calculadas sin identificarlas como errores exactos."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for column, (name, study) in enumerate(evidence["studies"].items()):
        rows = study["rows"]
        x = [row["grid_spacing_m"][0]*1000 if name == "spatial" else row["dt"] for row in rows]
        for index, metric in enumerate(("tmax", "delta")):
            ax = axes[index, column]
            values = [row[metric]["value_c"] for row in rows]
            ax.plot(x, values, "o-", color="#315cf2")
            for pos, value in zip(x, values):
                ax.annotate(f"{value:.4f}", (pos, value), xytext=(0, 8),
                            textcoords="offset points", ha="center", fontsize=9)
            ax.set(xlabel="Paso espacial x [mm]" if name == "spatial" else "Paso máximo [s]",
                   ylabel="T máxima [°C]" if metric == "tmax" else "ΔT máximo [°C]")
            ax.set_title("Espacial · Δt máximo 600 s" if name == "spatial" else "Temporal · malla 500 mm")
            ax.margins(x=.2, y=.3)
            ax.grid(alpha=.2)
            if metric == "delta":
                ax.axhline(20, color="#b45309", linestyle="--", label="Límite 20 °C")
                ax.legend(fontsize=8)
    fig.suptitle("S7 · muestra 46 · máximos simulados sobre 110 días")
    fig.tight_layout()
    fig.savefig(OUT / "convergence.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=float, choices=(2, 1, .5))
    parser.add_argument("--dt", type=float, choices=(1200, 600, 300))
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--weather-snapshot", help="Ensamble alternativo para una sensibilidad independiente")
    args = parser.parse_args()
    OUT = args.output
    if args.aggregate:
        aggregate()
    elif args.mesh is not None and args.dt is not None:
        run(args.mesh, args.dt, args.weather_snapshot)
    else:
        parser.error("Indicar --mesh y --dt, o --aggregate")
