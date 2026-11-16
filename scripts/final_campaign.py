"""Campaña G8 de planes y escenarios ponderados con resultados para el visor."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import csv
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import numpy as np

from scripts import e12_case, monte_carlo as mc, weather_3d
from thermal3d.construction import Pour, solve_construction
from thermal3d.critical_temperatures import CriticalTemperatures
from thermal3d.hydration import load_curves
from weather.series import FIELDS, HOUR, fill_tail, from_open_meteo, to_epoch
from weather.snapshots import load_snapshot

ROOT = mc.ROOT
SOURCE = ROOT / "data/hydration/source_terms.txt"
CONFIG = ROOT / "config/final_g8.json"


@lru_cache(maxsize=4)
def voxels(factor):
    return weather_3d.load_voxels(factor)


def schedule(plan, config, volumes):
    """Calcula tiempos respecto de t0, incluyendo espera anterior a la primera vertida."""
    pump_count = config["pump_count"]
    rate = pump_count * config["flow_m3_h_per_pump"]
    wait = config["minimum_wait_h"]
    if type(pump_count) is not int or pump_count < 1 or not np.isfinite([rate, wait]).all() or rate <= 0 or wait < 0:
        raise ValueError("Capacidad, bombas o espera mínima inválidas")
    volumes = np.asarray(volumes, dtype=float)
    if not len(volumes) or not np.isfinite(volumes).all() or np.any(volumes <= 0):
        raise ValueError(f"Plan {plan['id']}: todas las vertidas necesitan volumen positivo")
    durations = volumes / rate
    starts = plan.get("start_h")
    if starts is None:
        gap = plan["wait_h"]
        starts = [plan.get("first_start_h", 0)]
        for duration in durations[:-1]:
            starts.append(starts[-1] + duration + gap)
    if (len(starts) != len(volumes) or not np.isfinite(starts).all() or starts[0] < 0
            or any(b < a+d+wait-1e-9 for a, b, d in zip(starts, starts[1:], durations))):
        raise ValueError(f"Plan {plan['id']}: inicios incompatibles con capacidad o espera mínima")
    return [{"layer": i, "start_h": float(start), "finish_h": float(start+duration),
             "duration_h": float(duration), "volume_m3": float(volume)}
            for i, (start, duration, volume) in enumerate(zip(starts, durations, volumes), 1)]


def make_pours(plan, config):
    return [Pour(i, lo, hi, 0, plan.get("placement_c", config["placement_c"]))
            for i, (lo, hi) in enumerate(zip(plan["fractions"], plan["fractions"][1:]), 1)]


def reference_volumes(plan, config, geometry):
    component, spacing, _, _ = geometry
    fractions = (np.arange(component.shape[2])+.5)/component.shape[2]
    return [float(np.count_nonzero((component>0) & ((fractions>=p.z_min_fraction)&
             (fractions<p.z_max_fraction))[None,None,:])*np.prod(spacing)) for p in make_pours(plan, config)]


def progressive_plan(model, plan, config):
    result, _ = e12_case.build_plan_on_concrete(model, make_pours(plan, config))
    for row in plan["schedule"]:
        selected = result.vertida_id == row["layer"]
        counts = selected.sum(axis=(0, 1))
        mid = (counts.cumsum()-.5*counts)/counts.sum()
        hours = row["start_h"] + mid*row["duration_h"]
        result.start_s[selected] = np.broadcast_to(hours*HOUR, selected.shape)[selected]
    return result


@lru_cache(maxsize=4)
def weather_snapshot(folder):
    return load_snapshot(ROOT / folder)


def trim_missing_forecast_edges(series):
    """Separa nulos terminales del archivo de los huecos entre muestras válidas."""
    valid = np.flatnonzero(~series.missing())
    if len(valid) < 2:
        raise ValueError("El miembro no tiene una historia meteorológica utilizable")
    window = slice(valid[0], valid[-1]+1)
    return replace(series, time_s=series.time_s[window], origin=series.origin[window],
                   **{name:getattr(series,name)[window] for name in FIELDS})


@lru_cache(maxsize=64)
def forecast_member(folder, member):
    meta, payload = weather_snapshot(folder)
    return trim_missing_forecast_edges(from_open_meteo(payload, meta, member))


def make_weather(config, member, tail_method="persistencia"):
    meta, _ = weather_snapshot(config["weather_snapshot"])
    if (meta["latitude"], meta["longitude"]) != (-41.222539, -73.295603):
        raise ValueError("El snapshot no corresponde al punto docente G8")
    start = to_epoch(config["start_utc"])
    series = forecast_member(config["weather_snapshot"], member)
    if not series.start_s <= start <= series.end_s or start < to_epoch(meta["retrieved_at"]):
        raise ValueError("Se requiere un pronóstico disponible antes del inicio y con cobertura inicial")
    if "common_forecast_hours" in config:
        stop = np.searchsorted(series.time_s, start+config["common_forecast_hours"]*HOUR)
        series = replace(series, time_s=series.time_s[:stop], origin=series.origin[:stop],
                         **{field:getattr(series,field)[:stop] for field in FIELDS})
    return fill_tail(series, start, config["max_hours"]/24, method=tail_method), start


def choose_weather(config):
    _, payload = weather_snapshot(config["weather_snapshot"])
    names = [suffix for key in payload["hourly"] if key.startswith("temperature_2m_member")
             for suffix in [key[len("temperature_2m"):]]]
    ranked = []
    for member in sorted(names):
        series, start = make_weather(config, member)
        t = (series.time_s-start)/HOUR
        hours = (t >= 0) & (t < config["hours"]) & (np.asarray(series.origin) == "ensemble")
        if hours.any():
            air, wind, sun = (values[hours] for values in
                              (series.air_c, series.wind_10m_m_s, series.shortwave_w_m2))
            cold = air <= np.quantile(air, .25)
            ranked.append({"member": member, "mean_forecast_air_c": float(air.mean()),
                           "air_p10_c": float(np.quantile(air, .1)),
                           "wind_on_cold_hours_m_s": float(wind[cold].mean()),
                           "sun_mean_w_m2": float(sun.mean())})
    if len(ranked) < 3:
        raise ValueError("Se requieren al menos tres miembros utilizables del ensamble")
    ranked.sort(key=lambda row: (row["mean_forecast_air_c"], row["member"]))
    main = [{**ranked[i], "id": label, "weight": 1/3}
            for label, i in zip(("frío", "central", "cálido"),
                               (round(.1*(len(ranked)-1)), len(ranked)//2, round(.9*(len(ranked)-1))))]
    return main, ranked


def weather_sensitivity(main, ranked):
    """Elige perfiles omitidos según la combinación de dos rangos extremos."""
    members = {row["member"] for row in main}
    omitted = [row for row in ranked if row["member"] not in members]
    cases = []
    for label, criteria in (
        ("frío y ventoso", (("air_p10_c", False), ("wind_on_cold_hours_m_s", True))),
        ("cálido y soleado", (("mean_forecast_air_c", True), ("sun_mean_w_m2", True))),
    ):
        rank = {row["member"]: 0 for row in omitted}
        for key, descending in criteria:
            for i, row in enumerate(sorted(omitted, key=lambda x: x[key], reverse=descending)):
                rank[row["member"]] += i
        chosen = min(omitted, key=lambda row: rank[row["member"]])
        cases.append({**chosen, "id": label, "weight": 0, "tail_method": "persistencia"})
        omitted.remove(chosen)
    return [*cases, {**main[1], "id": "central · bloque de 72 h", "weight": 0, "tail_method": "bloque72"}]


def read_campaign(path):
    config = mc.read_json(path)
    return resolve_campaign(config)


def resolve_campaign(config):
    start = to_epoch(config["start_utc"])
    if not (to_epoch("2026-11-19T03:00Z") <= start < to_epoch("2026-11-20T03:00Z")):
        raise ValueError("t0 debe pertenecer al jueves 19 de noviembre en Santiago")
    config["start_local"] = datetime.fromtimestamp(start,timezone(timedelta(hours=-3))).isoformat()
    if not (config["hours"] == 336 and config["max_hours"] >= 360 and config["dt_s"] > 0):
        raise ValueError("Se requieren 14 días base y un horizonte ampliado posterior")
    geometry = voxels(1)
    for plan in config["plans"]:
        volumes = reference_volumes(plan, config, geometry)
        if plan.get("partition") == "equal_volume":
            volumes = [sum(volumes)/len(volumes)]*len(volumes)
        plan["schedule"] = schedule(plan, config, volumes)
        plan["duration_h"] = plan["schedule"][-1]["finish_h"]
        subbase_resistance = plan.get("subbase_r_m2k_w", 0)
        if not np.isfinite(subbase_resistance) or subbase_resistance < 0:
            raise ValueError(f"Plan {plan['id']}: resistencia de subbase inválida")
        if not (plan["duration_h"] <= min(plan["strip_h"], plan["top_remove_h"]) and
                max(plan["strip_h"], plan["top_remove_h"], plan["duration_h"]) + 72 <= config["max_hours"]):
            raise ValueError(f"Plan {plan['id']}: protección o horizonte incompatible con la colocación")
        if "blanket_core_stages" in plan and "blanket_stages" not in plan:
            raise ValueError(f"Plan {plan['id']}: la protección central requiere una periférica")
        for region in ("blanket_stages", "blanket_core_stages"):
            if region not in plan:
                continue
            stages = np.asarray(plan[region], dtype=float)
            if stages.ndim != 2 or stages.shape[0] < 2 or stages.shape[1] != 2:
                raise ValueError(f"Plan {plan['id']}: se requieren pares de hora y espesor")
            times, thicknesses = stages.T
            if (not np.isfinite([times, thicknesses]).all() or times[0] != 0
                    or times[-1] != plan["top_remove_h"] or np.any(np.diff(times) <= 0)
                    or thicknesses[-1] != 0 or np.any(thicknesses[:-1] <= 0)
                    or np.any(np.diff(thicknesses) > 0)):
                raise ValueError(f"Plan {plan['id']}: etapas de manta inválidas")
    return config


def temperature_rising(history, horizon):
    rows = list(history.values())
    def window(lo, hi):
        return np.asarray([[row["tmax_c"], row["delta_c"], *row["pour_tmax_c"]]
                           for row in rows if lo <= row["time_h"] < hi], dtype=float)
    prior, last = window(horizon-48, horizon-24), window(horizon-24, np.nextafter(horizon,np.inf))
    return not prior.size or not last.size or np.any(last.max(axis=0) > prior.max(axis=0)+.05)


def simulate(job, config, env, *, capture=False):
    began = perf_counter()
    plan = next(p for p in config["plans"] if p["id"] == job["plan"])
    if "placement_c" in job:
        plan = {**plan, "placement_c": job["placement_c"]}
    climate = job["climate"]
    series, start = make_weather(config, climate["member"], climate.get("tail_method", "persistencia"))
    curves, _ = load_curves(SOURCE, offset_h=config["offset_h"], tail_h=config["tail_h"])
    env = deepcopy(env)
    env["concrete"].update(config.get("mix", {}))
    if "soil_c" in job:
        env["soil"]["deep_temperature_c"] = job["soil_c"]
    hydration = curves[job["curve"]]
    if "heat_factor" in job:
        hydration = replace(hydration, source_w_m3=hydration.source_w_m3*job["heat_factor"])
    env["formwork"].update(strip_after_h=plan["strip_h"], blanket_after_strip=plan["side_blanket"],
                           use_bare_absorptance=True)
    if "side_blanket_m" in plan:
        env["formwork"]["blanket_thickness_m"] = plan["side_blanket_m"]
    env["insulation"]["remove_after_h"] = plan["top_remove_h"]
    protection_keys = ("blanket_stages", "blanket_core_stages")
    env["insulation"].update({key: plan[key] for key in protection_keys if key in plan})
    if "subbase_r_m2k_w" in plan:
        env["soil"]["subbase_r_m2k_w"] = plan["subbase_r_m2k_w"]
    baseline, maximum_h = config["hours"], config["max_hours"]
    last_event = max(plan["duration_h"], plan["strip_h"], plan["top_remove_h"])
    first_h = baseline if last_event+72 <= baseline else maximum_h
    day21 = config.get("report_21d", False)
    if day21:
        first_h = maximum_h
    critical_fields = {}
    protection_samples = []

    def run(hours):
        model = weather_3d.build_model(env, series, start, hours, voxels=voxels(job["mesh"]))
        p, concrete = model["p"], model["grid"]["concrete"]
        monitor = CriticalTemperatures(concrete, model["origin_m"], p.spacing_m)
        placement = progressive_plan(model, plan, config)
        pour_cells = [np.flatnonzero(placement.vertida_id == row["layer"]) for row in plan["schedule"]]
        checkpoints = {336: {}, 504: {}} if day21 else {baseline: {}}
        core_cell = weather_3d.locate_core_and_surface(model)["core"] if capture else None
        last_hour = -1
        near_removal = (plan["top_remove_h"]*HOUR - job["dt"], plan["top_remove_h"]*HOUR,
                        plan["top_remove_h"]*HOUR + HOUR, (plan["top_remove_h"]+24)*HOUR)

        def observe(time, temperature, active, domain):
            nonlocal last_hour
            previous_hot, previous_delta = monitor.tmax, monitor.delta
            monitor.observe(time, temperature, active, domain)
            hour = int(time/HOUR)
            if hour != last_hour and hour in monitor.hourly:
                last_hour = hour
                placed, field = active.ravel(), temperature.ravel()
                maxima = [float(field[cells][placed[cells]].max()) if placed[cells].any() else None for cells in pour_cells]
                monitor.hourly[hour]["pour_tmax_c"] = maxima
            if capture and hour in monitor.hourly and monitor.hourly[hour]["time_h"] == time/HOUR:
                monitor.hourly[hour]["core_c"] = float(temperature[core_cell]) if active[core_cell] else None
            if capture and time in near_removal and monitor.snapshot is not None:
                protection_samples.append(monitor.snapshot)
            for checkpoint, peaks in checkpoints.items():
                if time <= checkpoint*HOUR:
                    peaks.update(tmax=monitor.tmax, delta=monitor.delta)
            if capture:
                for key, previous in (("tmax",previous_hot), ("delta",previous_delta)):
                    if getattr(monitor,key) is not previous:
                        critical_fields[key] = np.where(active, temperature, np.nan).astype(np.float32)

        # Forzar exactamente t=336 h y los cambios de protección.
        events = (*(checkpoint*HOUR for checkpoint in checkpoints), plan["strip_h"]*HOUR, plan["top_remove_h"]*HOUR,
                  *(hour*HOUR for key in protection_keys for hour, _ in plan.get(key, ())))
        result = solve_construction(replace(p, dt_s=job["dt"]), placement,
                                    hydration, save_every=2**31,
                                    activation_energy_j_mol=config["activation_energy_j_mol"],
                                    hydration_reference_c=config.get("hydration_reference_c", 20.0),
                                    source_mask=concrete, initial_c=np.full(p.shape, env["soil"]["deep_temperature_c"]),
                                    observe_domain=observe, event_times_s=(*events, *near_removal))
        return model, monitor, result, checkpoints

    hours = first_h
    model, monitor, result, base = run(hours)
    if hours < maximum_h and (temperature_rising(monitor.hourly,hours) or
                              max(monitor.tmax["time_h"], monitor.delta["time_h"]) >= hours-24):
        hours = maximum_h
        protection_samples.clear()
        model, monitor, result, base = run(hours)
    open_peak = (temperature_rising(monitor.hourly,hours) or
                 max(monitor.tmax["time_h"], monitor.delta["time_h"]) >= hours-24)
    ifc = model["ifc_sha256"]
    counts = {k: int(sum(start <= t < start+hours*HOUR and o==k for t,o in zip(series.time_s,series.origin)))
              for k in sorted(set(series.origin))}
    saved_interval = float(np.max(np.diff(result.time_s)))
    row = {**job, "ifc_sha256": ifc, "weather_sha256": series.snapshot["sha256"], "hours": hours,
           "baseline": base[baseline], "tmax": monitor.tmax, "delta": monitor.delta, "horizon_open": bool(open_peak),
           "weather_hours": counts, "grid_spacing_m": model["spacing_m"].tolist(),
           "steps": result.step_count, "dt_mean_s": hours*HOUR/result.step_count,
           "run_seconds": perf_counter()-began,
           "max_saved_interval_s": saved_interval,
           "energy_error_relative": float(np.max(np.abs(result.energy_balance_error_j))/
                                          max(1, np.max(np.abs(result.energy_j))))}
    if day21:
        row["day21"] = base[504]
    if day21:
        row["voxel_pour_volumes_m3"] = reference_volumes(plan, config, voxels(job["mesh"]))
    if capture:
        row["protection_samples"] = protection_samples
        return row, model, monitor, critical_fields
    return row


def compare(plan, rows):
    hot = [row["tmax"]["value_c"] > 70 for row in rows]
    gradient = [row["delta"]["value_c"] > 20 for row in rows]
    weights = np.array([row["weight"] for row in rows])
    sensitivity = np.array([row["sensitivity_weight"] for row in rows])
    if (any(np.any(w < 0) or not np.isclose(w.sum(),1,atol=1e-12,rtol=0) for w in (weights,sensitivity))
            or len(rows) != len({(row["curve"],row["climate"]["id"]) for row in rows})):
        raise ValueError("Escenarios duplicados o pesos no normalizados")
    joint = np.logical_or(hot, gradient)
    risk = float(weights @ joint)
    closed = not any(row["horizon_open"] and w > 0 and not failed
                     for row,w,failed in zip(rows,weights,joint))
    checks = {}
    for row in rows:
        if "tail_method" in row["climate"]:
            check = checks.setdefault(row["climate"]["id"], {"runs": 0, "failures": 0,
                                      "max_t_c": -np.inf, "max_delta_c": -np.inf})
            check["runs"] += 1
            check["failures"] += int(row["fails"])
            check["max_t_c"] = max(check["max_t_c"], row["tmax"]["value_c"])
            check["max_delta_c"] = max(check["max_delta_c"], row["delta"]["value_c"])
    return {**plan, "prob_tmax": float(weights@hot), "prob_delta": float(weights@gradient),
            "prob_joint": risk, "prob_joint_all_curves": float(sensitivity@joint),
            "prob_joint_14d": float(weights @ np.array([r["baseline"]["tmax"]["value_c"]>70
                                                         or r["baseline"]["delta"]["value_c"]>20 for r in rows])),
            "feasible": bool(closed and risk <= .05), "classification_closed": closed, "climate_sensitivity": checks,
            "max_t_c": max(r["tmax"]["value_c"] for r in rows if r["weight"] > 0),
            "max_delta_c": max(r["delta"]["value_c"] for r in rows if r["weight"] > 0)}


def prepare(config_path, out, mesh):
    config = read_campaign(config_path)
    weather, ranked = choose_weather(config)
    stress = weather_sensitivity(weather, ranked) if config.get("weather_sensitivity") else []
    curves, audit = load_curves(SOURCE, offset_h=config["offset_h"], tail_h=config["tail_h"])
    if len({p["id"] for p in config["plans"]}) != len(config["plans"]):
        raise ValueError("IDs duplicados de planes")
    jobs = [{"plan": p["id"], "curve": name, "climate": climate, "mesh": mesh, "dt": config["dt_s"],
             "weight": climate["weight"]/4 if name.endswith("_SS") else 0,
             "sensitivity_weight": climate["weight"]/8}
            for p in config["plans"] for name in curves for climate in [*weather, *stress]
            if climate["weight"] > 0 or name.endswith("_SS")]
    metadata, _ = weather_snapshot(config["weather_snapshot"])
    manifest = {"config": config, "environment": mc.read_json(ROOT/"config/environment_g8.json"),
                "jobs": jobs, "weather": weather, "weather_sensitivity": stress, "weather_member_summary": ranked,
                "hydration_audit": audit, "weather_sha256": metadata["sha256"],
                "source_sha256": mc.digest(SOURCE), "ifc_sha256": voxels(1)[3], "code_sha256": mc.code_fingerprint()}
    out.mkdir(parents=True, exist_ok=False)
    mc.write_json(out/"manifest.json", manifest)
    return manifest


def task(out, index):
    manifest = mc.read_json(out/"manifest.json")
    if not 0 <= index < len(manifest["jobs"]):
        raise ValueError("Índice de escenario fuera de rango")
    path = mc.result_path(out,index)
    fingerprint = mc.digest(out/"manifest.json")
    if path.is_file():
        saved = mc.read_json(path)
        if saved["manifest_sha256"] != fingerprint:
            raise ValueError("La corrida pertenece a otro manifiesto")
        return saved
    if mc.digest(SOURCE)!=manifest["source_sha256"] or mc.code_fingerprint()!=manifest["code_sha256"]:
        raise ValueError("Cambió el código o la fuente de hidratación de la campaña")
    if manifest.get("numpy_version", np.__version__) != np.__version__:
        raise ValueError("La versión de NumPy cambió")
    row = simulate(manifest["jobs"][index], manifest["config"], manifest["environment"])
    if row["ifc_sha256"]!=manifest["ifc_sha256"] or row["weather_sha256"]!=manifest["weather_sha256"]:
        raise ValueError("Cambió el IFC o el pronóstico de la campaña")
    row.update(manifest_sha256=fingerprint,index=index,
               exceeds_tmax=row["tmax"]["value_c"]>70, exceeds_delta=row["delta"]["value_c"]>20)
    row["fails"] = row["exceeds_tmax"] or row["exceeds_delta"]
    mc.write_json(path, row)
    return row


def aggregate(out):
    manifest = mc.read_json(out/"manifest.json")
    fingerprint = mc.digest(out/"manifest.json")
    rows = [mc.read_json(mc.result_path(out,i)) for i in range(len(manifest["jobs"]))]
    for i, (row, job) in enumerate(zip(rows,manifest["jobs"])):
        if row["manifest_sha256"] != fingerprint or row["index"] != i or any(row[k]!=v for k,v in job.items()):
            raise ValueError(f"Resultado incompatible con el manifiesto: {i}")
    plans = [compare(plan,[r for r in rows if r["plan"]==plan["id"]]) for plan in manifest["config"]["plans"]]
    plans.sort(key=lambda plan: (plan["duration_h"],plan["id"]))
    chosen = next((p["id"] for p in plans if p["feasible"]),None)
    result = {"format":"mcoc-final-v1", "manifest_sha256": fingerprint, "plans":plans,
              "selected":chosen, "scenarios":rows, "config":manifest["config"], "weather":manifest["weather"],
              "weather_sensitivity": manifest.get("weather_sensitivity", []),
              "run_seconds": {"median": float(np.median([r["run_seconds"] for r in rows])),
                              "maximum": max(r["run_seconds"] for r in rows)},
              "hydration_audit":manifest["hydration_audit"],
              "weather_sha256":manifest["weather_sha256"], "source_sha256":manifest["source_sha256"]}
    mc.write_json(out/"comparison.json",result)
    tables = {
        "comparison.csv": [{k: plan[k] for k in ("id","duration_h","prob_tmax","prob_delta","prob_joint",
                                                  "prob_joint_all_curves","feasible")} for plan in plans],
        "scenarios.csv": [{**{k:r[k] for k in ("plan","curve","weight","sensitivity_weight","hours","fails",
                    "exceeds_tmax","exceeds_delta","horizon_open")}, "climate":r["climate"]["id"],
                    "tmax_c":r["tmax"]["value_c"],"tmax_h":r["tmax"]["time_h"],"tmax_xyz_m":r["tmax"]["xyz_m"],
                    "delta_c":r["delta"]["value_c"],"delta_h":r["delta"]["time_h"],
                    "delta_hot_xyz_m":r["delta"]["hot"]["xyz_m"],"surface25_xyz_m":r["delta"]["surface"]["xyz_m"]}
                   for r in rows],
    }
    for name, table in tables.items():
        with (out/name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream,fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare","run","local","aggregate","verify"))
    parser.add_argument("output",type=Path)
    parser.add_argument("--config",type=Path,default=CONFIG)
    parser.add_argument("--mesh",type=float,choices=(.5,1,2),default=1)
    parser.add_argument("--index",type=int,default=0)
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    if args.action=="prepare":
        print("Escenarios:",len(prepare(args.config,args.output,args.mesh)["jobs"]))
    elif args.action=="run":
        print(task(args.output,args.index)["index"])
    elif args.action=="local":
        from itertools import repeat
        count=len(mc.read_json(args.output/"manifest.json")["jobs"])
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for i,_ in enumerate(pool.map(task,repeat(args.output),range(count)),1):
                if i%8==0 or i==count:
                    print(f"{i}/{count}",flush=True)
    elif args.action=="aggregate":
        print("Plan:",aggregate(args.output)["selected"])
    else:
        from scripts.final_verification import verify
        verify(args.output)


if __name__ == "__main__":
    main()
