"""Monte Carlo, cribado y decisión sobre el mismo modelo físico de campaña G8."""

import argparse
import csv
from itertools import product
from math import exp, fsum, lgamma, log, log1p
from pathlib import Path

import numpy as np

from scripts import final_campaign as campaign, monte_carlo as io
from thermal3d.hydration import load_curves
from weather.series import HOUR, from_open_meteo, to_epoch

CONFIG = campaign.ROOT / "config/monte_carlo_final_g8.json"


def read_settings(path):
    settings = io.read_json(path)
    parent = settings.pop("extends", None)
    if parent:
        return {**io.read_json(path.parent/parent), **settings}
    return settings


def complete_members(config, minimum_hours):
    """Exige datos de aire, viento y radiación en una ventana horaria desde t₀."""
    meta, payload = campaign.weather_snapshot(config["weather_snapshot"])
    prefix = "temperature_2m"
    names = sorted(key[len(prefix):] for key in payload["hourly"] if key.startswith(prefix+"_member"))
    if prefix in payload["hourly"]:
        names.insert(0, "")
    start = to_epoch(config["start_utc"])
    end_by_member = {}
    for member in names:
        series = from_open_meteo(payload, meta, member)
        index = np.searchsorted(series.time_s, start)
        if index == series.time_s.size or series.time_s[index] != start:
            continue
        missing = np.flatnonzero(series.missing()[index:])
        contiguous = int(missing[0]) if missing.size else series.time_s.size-index
        if contiguous >= minimum_hours:
            end_by_member[member] = contiguous
    if not end_by_member:
        raise ValueError("No hay miembros completos para la ventana mínima")
    common = int(min(end_by_member.values()))
    return sorted(end_by_member), common, sorted(set(names)-end_by_member.keys())


def draws(settings, members, curves, size, seed):
    curve_rng, weather_rng, heat_rng, temp_rng, soil_rng, control_rng = [
        np.random.default_rng(child) for child in np.random.SeedSequence(seed).spawn(6)]
    uniform = settings["uniform"]
    numbered = [member for member in members if member]
    weather = weather_rng.choice(numbered or members, size=size)
    # Al habilitar el control se conserva la realización numerada si no se elige
    # el control. Con probabilidad 1/N para el control, todos tienen masa 1/N.
    if "" in members:
        weather[control_rng.random(size) < 1/len(members)] = ""
    return [{"curve": str(curve), "member": str(member), "heat_factor": float(heat),
             "placement_offset_c": float(offset), "soil_c": float(soil)}
            for curve, member, heat, offset, soil in zip(
                curve_rng.choice(curves, size=size), weather,
                heat_rng.uniform(*uniform["heat_factor"], size=size),
                temp_rng.uniform(*uniform["placement_offset_c"], size=size),
                soil_rng.uniform(*uniform["soil_c"], size=size))]


def equal_volume_fractions(geometry):
    component, _, _, _ = geometry
    cell_counts = (component > 0).sum(axis=(0, 1))
    faces = np.arange(len(cell_counts)+1)/len(cell_counts)
    cumulative = np.r_[0, np.cumsum(cell_counts)]
    return np.interp(cumulative[-1]*np.arange(4)/3, cumulative, faces).tolist()


def grid_plans(settings):
    spec = settings["screen"]
    partitions = {"3h": (np.arange(4)/3).tolist(), "3v": equal_volume_fractions(campaign.voxels(.5)),
                  "4h": (np.arange(5)/4).tolist(), "5h": (np.arange(6)/5).tolist()}
    plans = []
    for temp, thickness, removal, partition, mode in product(
            spec["placement_c"], spec["blanket_mm"], spec["removal_h"], spec["partitions"], spec["removal_modes"]):
        meters = thickness/1000
        stages = [[0, meters]]
        if mode == "staged":
            stages.append([removal-48, meters/2])
        stages.append([removal, 0])
        ident = f"{partition}-{temp}C-{thickness}mm-{removal}h-{mode}"
        plans.append({"id": ident, "label": ident, "fractions": partitions[partition],
                      "partition": "equal_volume" if partition == "3v" else "equal_height",
                      "wait_h": 6, "placement_c": temp, "strip_h": 96, "top_remove_h": removal,
                      "side_blanket": True, "blanket_stages": stages})
    return plans


def _binomial_tail(k, n, p, upper):
    if p == 0:
        return float(not upper or k == 0)
    if p == 1:
        return float(upper or k == n)
    low, high = (k, n) if upper else (0,k)
    terms = [lgamma(n+1)-lgamma(x+1)-lgamma(n-x+1)+x*log(p)+(n-x)*log1p(-p)
             for x in range(low,high+1)]
    peak = max(terms)
    return min(1.0, exp(peak)*fsum(exp(x-peak) for x in terms))


def clopper_pearson(k, n):
    if not 0 <= k <= n or n == 0:
        raise ValueError("Conteo binomial inválido")

    def solve(upper):
        lo, hi = 0., 1.
        for _ in range(55):
            p = (lo+hi)/2
            if (_binomial_tail(k,n,p,upper) < .025) == upper:
                lo = p
            else:
                hi = p
        return (lo+hi)/2

    return [solve(True) if k else 0., solve(False) if k<n else 1.]


def metrics(rows, checkpoint=None):
    peaks = [row[checkpoint] if checkpoint else row for row in rows]
    t = np.array([row["tmax"]["value_c"] for row in peaks])
    d = np.array([row["delta"]["value_c"] for row in peaks])
    hot, gradient = t > 70, d > 20
    result = {}
    for key, flags in (("tmax",hot),("delta",gradient),("joint",hot | gradient)):
        count = int(np.count_nonzero(flags))
        result[key] = {"failures": count, "n": len(rows), "p": count/len(rows),
                       "ci95": clopper_pearson(count,len(rows))}
    for key, values in (("tmax",t),("delta",d)):
        result[key].update(zip(("p05","p50","p95"), np.quantile(values,[.05,.5,.95]).tolist()))
    result["open_horizons"] = sum(row["horizon_open"] for row in rows) if checkpoint is None else None
    return result


def _job(plan, realization, settings, index=0):
    return {"plan": plan["id"], "curve": realization["curve"], "climate": {
                "member": realization["member"], "id": realization["member"] or "control"},
            "heat_factor": realization["heat_factor"], "soil_c": realization["soil_c"],
            "placement_c": plan.get("placement_c",20)+realization.get("placement_offset_c",0),
            "sample_id": index, "mesh": settings["mesh"], "dt": settings["dt_s"]}


def prepare(out, settings, phase, shortlist=None, variant="base", size=None):
    candidate = settings.get("candidate_campaign")
    config = io.read_json(campaign.CONFIG.parent/candidate if candidate else campaign.CONFIG)
    refs = [plan for plan in config["plans"] if plan["id"] in {"C","C3"}]
    if phase == "screen":
        config["plans"] = grid_plans(settings) + refs
    else:
        options = shortlist if shortlist is not None else config["plans"]
        config["plans"] = [plan for plan in options if phase != "confirm" or plan["id"] in settings["confirm_ids"]]
        for plan in config["plans"]:
            plan.setdefault("placement_c", config["placement_c"])
    config.update(weather_snapshot=settings["weather_snapshot"], report_21d=True,
                  max_hours=settings["end_h"], dt_s=settings["dt_s"], mix={**settings["mix"]},
                  hydration_reference_c=settings["hydration_reference_c"])
    if variant == "mix":
        config["mix"].update(settings["mix_sensitivity"])
    if variant == "ea":
        config["activation_energy_j_mol"] = settings["activation_energy_sensitivity_j_mol"]
    config = campaign.resolve_campaign(config)
    members, common, excluded = complete_members(config,settings["minimum_common_forecast_hours"])
    config["common_forecast_hours"] = common
    curves, audit = load_curves(campaign.SOURCE, offset_h=config["offset_h"], tail_h=config["tail_h"])
    seed = settings["confirmation_seed"] if phase == "confirm" else settings["seed"]
    if phase == "screen":
        spec = settings["screen"]
        samples = [{key: spec[key] for key in ("curve","member","heat_factor","soil_c")}]
    else:
        size = size or (settings["samples"] if variant == "base" else settings["sensitivity_samples"])
        if size < 1 or not config["plans"]:
            raise ValueError("Se requiere un lote positivo y al menos un plan")
        names = list(curves) if variant=="curves" else [name for name in curves if name.endswith("_SS")]
        samples = draws(settings,members,names,size,seed)
    jobs = [_job(plan,sample,settings,i) for plan in config["plans"] for i,sample in enumerate(samples)]
    metadata, _ = campaign.weather_snapshot(config["weather_snapshot"])
    manifest = {"phase":phase, "variant":variant, "seed":seed, "settings":settings, "config":config,
                "environment":io.read_json(campaign.ROOT/"config"/settings.get("environment_config", "environment_g8.json")), "jobs":jobs,
                "weather_members":members, "excluded_weather_members":excluded, "common_forecast_hours":common,
                "hydration_audit":audit, "weather_sha256":metadata["sha256"],
                "source_sha256":io.digest(campaign.SOURCE), "ifc_sha256":campaign.voxels(1)[3],
                "code_sha256":io.code_fingerprint(), "numpy_version":np.__version__}
    out.mkdir(parents=True,exist_ok=False)
    io.write_json(out/"manifest.json",manifest)
    return len(jobs)


def collect(out):
    manifest = io.read_json(out/"manifest.json")
    digest = io.digest(out/"manifest.json")
    rows = [io.read_json(io.result_path(out,i)) for i in range(len(manifest["jobs"]))]
    for i,(row,job) in enumerate(zip(rows,manifest["jobs"])):
        if row["index"]!=i or row["manifest_sha256"]!=digest or any(row[k]!=v for k,v in job.items()):
            raise ValueError(f"Resultado inválido para la muestra {i}")
    return manifest, rows


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(out):
    manifest, rows = collect(out)
    plans = manifest["config"]["plans"]
    if manifest["phase"] == "screen":
        by_id = {row["plan"]:row for row in rows}
        ranked = []
        for plan in plans:
            row = by_id[plan["id"]]
            t,d = row["tmax"]["value_c"],row["delta"]["value_c"]
            ranked.append({"id":plan["id"], "duration_h":plan["duration_h"], "tmax_c":t, "delta_c":d,
                           "outside_c":max(0.,t-70,d-20), "horizon_open":row["horizon_open"]})
        ranked.sort(key=lambda row: (row["horizon_open"],row["outside_c"],row["duration_h"],row["delta_c"],row["id"]))
        refs = {"C","C3"}
        ids = set(row["id"] for row in ranked if row["id"] not in refs)
        nominees = [row["id"] for row in ranked if row["id"] in ids][:manifest["settings"]["screen"]["nominees"]]
        io.write_json(out/"shortlist.json",[plan for plan in plans if plan["id"] in {*refs,*nominees}])
        write_csv(out/"screen.csv",ranked)
        return nominees
    summaries = []
    for plan in plans:
        chosen = [row for row in rows if row["plan"]==plan["id"]]
        final = metrics(chosen)
        summaries.append({**plan,"statistics":{"day14":metrics(chosen,"baseline"),
                                               "day21":metrics(chosen,"day21"), "final":final},
                          "feasible":len(chosen)>=100 and not final["open_horizons"] and final["joint"]["ci95"][1]<.05})
    summaries.sort(key=lambda plan:(plan["duration_h"],plan["statistics"]["final"]["joint"]["ci95"][1],plan["id"]))
    selected = next((p["id"] for p in summaries if p["feasible"]),None)
    best = min(summaries,key=lambda p:(p["statistics"]["final"]["joint"]["p"],
               p["statistics"]["final"]["delta"]["p95"],p["duration_h"],p["id"]))["id"]
    result = {"format":"mcoc-monte-carlo-v1", "manifest_sha256":io.digest(out/"manifest.json"),
              "phase":manifest["phase"],"variant":manifest["variant"],"seed":manifest["seed"],
              "selected":selected,"best_relative":best,"plans":summaries,"config":manifest["config"],
              "weather_members":manifest["weather_members"],"common_forecast_hours":manifest["common_forecast_hours"],
              "weather_sha256":manifest["weather_sha256"],"source_sha256":manifest["source_sha256"],
              "code_sha256":manifest["code_sha256"],"ifc_sha256":manifest["ifc_sha256"]}
    io.write_json(out/"comparison.json",result)
    write_csv(out/"comparison.csv",[{"plan":p["id"],"duration_h":p["duration_h"],"period":period,
              "kind":kind,**stats,"feasible":p["feasible"]}
              | ({"p05":"","p50":"","p95":""} if kind=="joint" else {})
              for p in summaries for period,group in p["statistics"].items()
              for kind,stats in group.items() if kind!="open_horizons"])
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("screen","sample","confirm","aggregate"))
    parser.add_argument("output",type=Path)
    parser.add_argument("--config",type=Path,default=CONFIG)
    parser.add_argument("--shortlist",type=Path)
    parser.add_argument("--variant",choices=("base","curves","mix","ea"),default="base")
    parser.add_argument("--size",type=int)
    parser.add_argument("--plan")
    args = parser.parse_args()
    if args.action=="aggregate":
        print("Selección:",aggregate(args.output))
        return
    settings = read_settings(args.config)
    shortlist = io.read_json(args.shortlist) if args.shortlist else None
    if args.action!="screen" and not shortlist and "candidate_campaign" not in settings:
        parser.error("--shortlist es requerido si el JSON no define una campaña candidata")
    if args.action=="confirm":
        if not args.plan:
            parser.error("--plan es requerido para la confirmación")
        settings["confirm_ids"] = [args.plan]
    count = prepare(args.output,settings,args.action,shortlist,variant=args.variant,size=args.size)
    print("Tareas:",count)


if __name__ == "__main__":
    main()
