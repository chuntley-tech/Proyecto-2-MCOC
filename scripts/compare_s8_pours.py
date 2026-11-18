"""Compara diez planes de S8 en tres resoluciones, con procesos independientes."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import os
from pathlib import Path

from scripts import final_campaign as campaign, monte_carlo as io, weather_3d
from scripts.converge_s8 import assess, fixed_protection, geometry
from scripts.verify_s7 import inputs, LOT

ROOT = campaign.ROOT
OUT = ROOT / "results/final/s8_pour_comparison"
MESHES = (24, 48, 96)
FORECAST = "data/weather/2026-11-17T1622Z_ensemble"

# Las temperaturas de descarga son supuestos de operación, independientes del aire.
# Los tiempos de inicio están en horas desde el 19 de noviembre a las 08:00.
CASES = (
    ("S8-V01", (0, 1), (0,), 14),
    ("S8-V02", (0, 1), (0,), 16),
    ("S8-V03", (0, 1), (4,), 16),
    ("S8-V04", (0, 1/3, 1), (0, 24), 14),
    ("S8-V05", (0, 1/3, 1), (0, 28), 16),
    ("S8-V06", (0, 1/3, 1), (4, 48), 15),
    ("S8-V07", (0, 2/3, 1), (0, 24), 15),
    ("S8-V08", (0, 1/3, 2/3, 1), (0, 24, 48), 14),
    ("S8-V09", (0, 1/3, 2/3, 1), (4, 28, 52), 16),
    ("S8-V10", (0, 1/3, 2/3, 1), (0, 36, 60), 15),
)


def setup():
    original, reference = inputs()
    source = io.digest(campaign.SOURCE)
    if source != original["source_sha256"]:
        raise ValueError("La fuente de calor difiere de la referencia")
    config = io.read_json(ROOT / "config/final_g8_s8.json")
    template = config["plans"][0]
    config.update(weather_snapshot=FORECAST, common_forecast_hours=373, dt_s=600)
    config["plans"] = [
        {**deepcopy(template), "id": name, "label": name, "fractions": list(fractions),
         "start_h": list(starts), "placement_c": temperature}
        for name, fractions, starts, temperature in CASES
    ]
    # El volumen de la grilla de referencia fija la duración de cada vertida
    # para las tres mallas. Los cortes a 1,10 y 2,20 m caen sobre caras.
    config = campaign.resolve_campaign(config)
    env = io.read_json(ROOT / "config/environment_s8.json")
    job = original["jobs"][reference["base"]["index"]]
    series, start = campaign.make_weather(config, job["climate"]["member"])
    air = series.boundary_functions(start)["air_c"]
    forecast_at_start = {
        plan["id"]: [float(air(pour["start_h"]*3600)) for pour in plan["schedule"]]
        for plan in config["plans"]
    }
    jobs = [
        {**job, "plan": plan["id"], "mesh": n, "dt": config["dt_s"], "placement_c": plan["placement_c"]}
        for n in reversed(MESHES) for plan in config["plans"]
    ]
    return {"config": config, "environment": env, "jobs": jobs, "forecast_air_at_pour_start_c": forecast_at_start,
            "source_sha256": source, "weather_sha256": series.snapshot["sha256"],
            "ifc_sha256": original["ifc_sha256"], "reference_manifest_sha256": io.digest(LOT/"manifest.json")}


def build_model(*args, **kwargs):
    return fixed_protection(weather_3d.build_model(*args, **kwargs))


def run_one(out, manifest, job):
    path = out / f'{job["plan"]}_n{job["mesh"]}.json'
    if path.is_file():
        saved = io.read_json(path)
        if saved["manifest_sha256"] != io.digest(out/"manifest.json"):
            raise ValueError(f"Resultado de otro manifiesto: {path}")
        return saved
    print(f'Iniciando {job["plan"]} · {job["mesh"]} celdas en x e y', flush=True)
    row = campaign.simulate(job, manifest["config"], manifest["environment"],
                            voxel_loader=geometry, model_builder=build_model)
    for key in ("weather_sha256", "ifc_sha256"):
        if row[key] != manifest[key]:
            raise ValueError(f"Cambió el insumo {key}")
    result = {"row": row, "manifest_sha256": io.digest(out/"manifest.json")}
    io.write_json(path, result)
    return result


def aggregate(out):
    manifest = io.read_json(out/"manifest.json")
    fingerprint = io.digest(out/"manifest.json")
    rows = {}
    for job in manifest["jobs"]:
        path = out / f'{job["plan"]}_n{job["mesh"]}.json'
        if path.is_file():
            saved = io.read_json(path)
            if saved["manifest_sha256"] != fingerprint or any(saved["row"][k] != v for k,v in job.items()):
                raise ValueError(f"Resultado inválido: {path}")
            rows[job["plan"],job["mesh"]] = saved["row"]
    plans, table = [], []
    for plan in manifest["config"]["plans"]:
        completed = [rows[plan["id"],n] for n in MESHES if (plan["id"],n) in rows]
        fits = {key: assess([row[key]["value_c"] for row in completed])
                for key in ("delta","tmax")} if len(completed)==len(MESHES) else {}
        plans.append({"plan": plan, "meshes": completed, "apparent_convergence": fits,
                      "air_at_pour_start_c": manifest["forecast_air_at_pour_start_c"][plan["id"]]})
        for row in completed:
            table.append({"plan":plan["id"],"pours":len(plan["schedule"]),"duration_h":plan["duration_h"],
                          "placement_c":row["placement_c"],"horizontal_cells":row["mesh"],
                          "spacing_mm": [round(v*1000,4) for v in row["grid_spacing_m"]],
                          "tmax_c":row["tmax"]["value_c"],"delta_c":row["delta"]["value_c"],
                          "peak_delta_h":row["delta"]["time_h"],"horizon_open":row["horizon_open"],
                          "under_limits":row["tmax"]["value_c"]<=70 and row["delta"]["value_c"]<=20})
    if table:
        from scripts.final_mc import write_csv
        write_csv(out/"comparison.csv",table)
    io.write_json(out/"summary.json",{"completed":len(rows),"expected":len(manifest["jobs"]),
                                    "plans":plans,"manifest_sha256":fingerprint})
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 1,30,61))
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args()
    out = args.output
    if args.aggregate:
        print(f"Agregadas {aggregate(out)}/30 simulaciones")
        return
    if not 1 <= args.workers <= 61:
        parser.error("--workers debe estar entre 1 y 61")
    # Una simulación por proceso. Evita que cada biblioteca numérica vuelva
    # a crear un grupo de hilos y sature los núcleos asignados.
    for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    manifest = setup()
    if (out/"manifest.json").is_file():
        if io.read_json(out/"manifest.json") != manifest:
            raise ValueError("La carpeta corresponde a otros insumos")
    else:
        io.write_json(out/"manifest.json",manifest)
    print(f'{len(manifest["jobs"])} cálculos, {args.workers} procesos',flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one,out,manifest,job) for job in manifest["jobs"]]
        for index,future in enumerate(as_completed(futures),1):
            row = future.result()["row"]
            print(f'{index}/{len(futures)} | {row["plan"]} n={row["mesh"]} | delta T={row["delta"]["value_c"]:.4f} C', flush=True)
    aggregate(out)


if __name__ == "__main__":
    main()
