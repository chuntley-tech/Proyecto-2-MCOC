"""E12: caso determinista de 14 días con vertidas, hidratación, suelo y clima real.

Une el pipeline E11 (IFC + suelo + bordes ambientales) con el plan de vertidas
de construction_g8.json. La hidratación usa la curva adiabática exponencial del
curso (theta_inf = 45 °C, tau = 30 h) y edad equivalente de Arrhenius. El suelo
está activo desde t = 0 a la temperatura profunda, pero no recibe fuente ni
envejece (source_mask = hormigón).

    python -m scripts.fetch_weather --days 16
    python -m scripts.e12_case

Los resultados quedan en results/e12_14d/<snapshot>/.
"""

import argparse
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts import view_3d, weather_3d
from scripts.voxelize_foundation import case_ifc
from thermal3d.construction import (ConstructionPlan, ExponentialAdiabaticHydration, Pour, build_plan,
                                    solve_construction)
from thermal3d.solver import prepare
from thermal3d.voxel import load_ifc_meshes
from thermal3d.vtk_export import write_pvd, write_vti
from weather.series import HOUR, coverage, fill_tail, to_iso

ROOT_DIR = Path(__file__).resolve().parents[1]
FILL_ORIGINS = {"persistencia", "climatologia", "conservador"}


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_weather(config, args, hours):
    """Snapshot real, t0 = primera hora completa después de la descarga, y cola rellenada."""
    namespace = SimpleNamespace(synthetic=args.synthetic, start=args.start, snapshot=args.snapshot)
    series, metadata, start = weather_3d.load_weather(namespace, config)
    days = hours / 24.0
    before = coverage(series, start, days)
    filled = False
    if not before["complete"]:
        series = fill_tail(series, start, days, method="persistencia")
        filled = True
    after = coverage(series, start, days)
    if not after["complete"]:
        raise ValueError("La serie rellenada todavía no cubre el período solicitado")
    window = (series.time_s >= start - 1e-6) & (series.time_s < start + hours * HOUR - 1e-6)
    origins = np.asarray(series.origin)[window]
    fill_mask = np.isin(origins, list(FILL_ORIGINS))
    tail_times = series.time_s[window][fill_mask]
    info = {
        "coverage_before_fill": before,
        "coverage_after_fill": after,
        "filled": filled,
        "tail_method": "persistencia" if fill_mask.any() else None,
        "forecast_hours": int(np.count_nonzero(~fill_mask)),
        "tail_hours": int(np.count_nonzero(fill_mask)),
        "tail_from_utc": to_iso(float(tail_times.min())) if tail_times.size else None,
        "tail_from_s": float(tail_times.min()) if tail_times.size else None,
        "origin_hours_in_window": {name: int(np.count_nonzero(origins == name))
                                   for name in sorted(set(origins.tolist()))},
    }
    return series, metadata, start, info


def build_plan_on_concrete(model, pours):
    """Plan con fracciones z relativas a la altura del hormigón, no del dominio con suelo."""
    grid, p = model["grid"], model["p"]
    concrete = grid["concrete"]
    spacing = p.spacing_m
    columns = concrete.any(axis=(0, 1))
    occupied = np.flatnonzero(columns)
    if not occupied.size or occupied[-1] - occupied[0] + 1 != occupied.size:
        raise ValueError("El hormigón no forma una franja vertical continua en la grilla")
    z0, z1 = int(occupied[0]), int(occupied[-1]) + 1
    sub_grid = SimpleNamespace(
        component=concrete[:, :, z0:z1].astype(np.int16),
        active=concrete[:, :, z0:z1],
        origin_m=np.asarray(model["origin_m"], dtype=float) + np.array([0.0, 0.0, z0 * spacing[2]]),
        lengths_m=np.array([p.lengths_m[0], p.lengths_m[1], (z1 - z0) * spacing[2]], dtype=float),
        spacing_m=spacing,
    )
    sub_plan = build_plan(sub_grid, pours)
    shape = tuple(p.shape)
    ids = np.zeros(shape, dtype=np.int32)
    starts = np.full(shape, np.inf)
    temperatures = np.zeros(shape)
    ids[:, :, z0:z1] = sub_plan.vertida_id
    starts[:, :, z0:z1] = sub_plan.start_s
    temperatures[:, :, z0:z1] = sub_plan.placement_c
    plan = ConstructionPlan(ids, starts, temperatures, sub_plan.rows)
    return plan, {"z_cells": [z0, z1], "concrete_height_m": float((z1 - z0) * spacing[2]),
                  "z_min_m": float(model["origin_m"][2] + z0 * spacing[2]),
                  "z_max_m": float(model["origin_m"][2] + z1 * spacing[2])}


def check_plan_volume(plan, concrete, spacing, ifc_sha256):
    """Volumen del plan = volumen de hormigón voxelizado; compara con la triangulación IFC."""
    layer_volume = float(sum(float(row["volume_m3"]) for row in plan.rows))
    voxel_volume = float(np.count_nonzero(concrete) * np.prod(spacing))
    if not math.isclose(layer_volume, voxel_volume, rel_tol=1e-12):
        raise ValueError("Los volúmenes de las vertidas no suman el hormigón voxelizado")
    ifc_path, guids = case_ifc(ROOT_DIR / "config" / "case_g8.json")
    meshes, source = load_ifc_meshes(ifc_path, guids)
    if source["sha256"] != ifc_sha256:
        raise ValueError("El IFC cambió durante la simulación")
    ifc_volume = float(sum(mesh.volume_m3 for mesh in meshes))
    return {
        "ifc_volume_m3": ifc_volume,
        "voxel_volume_m3": voxel_volume,
        "layers_volume_m3": layer_volume,
        "layers_equal_voxel": True,
        "relative_error_vs_ifc": abs(layer_volume - ifc_volume) / ifc_volume,
        "scope": ("La suma de vertidas coincide con el hormigón voxelizado; la diferencia con la "
                  "triangulación IFC es el error de discretización de la grilla (dx = 0.25 m)."),
    }


def fields(model, places, material, temperature, active):
    return {
        "temperature": np.where(active, temperature, np.nan).astype(np.float32),
        "material": material.astype(np.int8),
        "component_ifc": model["component"].astype(np.int16),
        "zone": places["zone"],
        "depth_to_boundary_m": places["depth_m"].astype(np.float32),
        "active": active.astype(np.uint8),
    }


def cell_centre(model, cell):
    return [float(o + (i + 0.5) * d) for o, i, d in zip(model["origin_m"], cell, model["p"].spacing_m)]


def frame_metrics(model, places, temperature, active):
    concrete = model["grid"]["concrete"]
    placed = active & concrete
    masked = np.where(placed, temperature, -np.inf)
    hot = np.unravel_index(int(np.argmax(masked)), masked.shape)
    surface = placed & (places["zone"] == weather_3d.ZONE["superficie"])
    cold = None
    if surface.any():
        cold = np.unravel_index(int(np.argmin(np.where(surface, temperature, np.inf))), temperature.shape)
    return {
        "placed_cells": int(np.count_nonzero(placed)),
        "tmax_c": float(temperature[hot]),
        "tmax_cell": tuple(int(v) for v in hot),
        "tmax_xyz_m": cell_centre(model, hot),
        "surface_cells": int(np.count_nonzero(surface)),
        "tmin_surface_c": float(temperature[cold]) if cold is not None else None,
        "tmin_surface_cell": tuple(int(v) for v in cold) if cold is not None else None,
        "tmin_surface_xyz_m": cell_centre(model, cold) if cold is not None else None,
    }


def plot_hydration(path, hydration):
    age_h = np.linspace(0.0, 14.0 * 24.0, 700)
    theta = hydration.theta_ad_c(age_h * HOUR)
    q = hydration.rate(age_h * HOUR)
    fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
    ax.plot(age_h, theta, color="tab:red", label=r"$\theta_{ad}$")
    ax.set(xlabel="edad equivalente [h]", ylabel="elevación adiabática [°C]")
    ax.grid(alpha=0.3)
    twin = ax.twinx()
    twin.plot(age_h, q, color="tab:orange", ls="--", label=r"$\dot q_h$")
    twin.set_ylabel("fuente de hidratación [W/m³]")
    ax.axvline(hydration.tau_s / HOUR, color="gray", ls=":", label=r"$\tau$ = 30 h")
    fig.suptitle(f"Hidratación: theta_inf = {hydration.theta_inf_c:g} °C, tau = {hydration.tau_s/HOUR:g} h, "
                 f"rho·cp·theta_inf/tau = {hydration.rate(0.0):.0f} W/m³")
    lines = ax.get_lines() + twin.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], loc="center right", fontsize=8)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_weather(path, series, metadata, start, hours, info):
    t = (series.time_s - start) / HOUR
    selection = (t >= -2) & (t <= hours + 2)
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout="constrained")
    axes[0].plot(t[selection], series.air_c[selection], color="tab:blue")
    axes[0].set_ylabel("aire 2 m [°C]")
    axes[1].plot(t[selection], series.wind_10m_m_s[selection], color="tab:green")
    axes[1].set_ylabel("viento 10 m [m/s]")
    axes[2].step(t[selection], series.shortwave_w_m2[selection], where="pre", color="goldenrod")
    axes[2].set_ylabel("onda corta [W/m²]")
    axes[2].set_xlabel("horas desde t = 0")
    for ax in axes:
        ax.axvspan(0, hours, color="tab:red", alpha=0.08, label="período simulado")
        ax.grid(alpha=0.3)
    if info["tail_from_s"] is not None:
        tail_h = (info["tail_from_s"] - start) / HOUR
        for ax in axes:
            ax.axvline(tail_h, color="tab:red", ls="--", lw=1.2, label="inicio del relleno")
        note = f"relleno: {info['tail_hours']} h desde {info['tail_from_utc']}"
    else:
        note = "serie completa: sin relleno"
    axes[0].set_title(f"Clima 14 d — {metadata.get('folder') or 'SINTÉTICO'}  ·  "
                      f"{info['forecast_hours']} h pronóstico / {info['tail_hours']} h relleno\n"
                      f"descargado {metadata.get('retrieved_at')}  ·  t = 0 = {to_iso(start)}  ·  {note}", fontsize=9)
    axes[0].legend(loc="upper right", fontsize=8)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_core_surface(path, history, metadata, start):
    t = history["t_h"]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
    ax = axes[0]
    ax.plot(t, history["aire_c"], color="tab:blue", lw=1, label="aire")
    ax.plot(t, history["tmax_c"], color="k", lw=1.5, label="T máx hormigón")
    ax.plot(t, history["tmin_superficie_c"], color="tab:red", lw=1.2, label="T mín superficie (zone = 2)")
    ax.plot(t, history["nucleo_c"], color="tab:purple", label="núcleo geométrico")
    ax.plot(t, history["sonda_superior_c"], color="tab:orange", label="sonda superior")
    ax.plot(t, history["sonda_lateral_c"], color="tab:cyan", label="sonda lateral")
    ax.axhline(70.0, color="tab:red", ls="--", lw=1, label="70 °C")
    ax.set(ylabel="temperatura [°C]", title=f"Núcleo, superficie y máximo — {metadata.get('folder') or 'SINTÉTICO'}")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3, fontsize=7, loc="upper left")
    lower = axes[1]
    lower.plot(t, history["delta_t_c"], color="tab:brown", lw=1.4, label="ΔT = Tmax − Tmin superficie")
    lower.axhline(20.0, color="tab:red", ls="--", lw=1, label="criterio 20 °C")
    lower.set(xlabel="horas desde t = 0", ylabel="ΔT [°C]")
    lower.grid(alpha=0.3)
    lower.legend(fontsize=8, loc="upper left")
    fig.savefig(path, dpi=140)
    plt.close(fig)


def boundary_record(face, times):
    rows = {}
    for label, time_s in times.items():
        described = face.describe(time_s)
        described.update({
            "absortancia": face.solar_absorptance,
            "factor_solar": face.solar_factor,
            "capas_R": [{"nombre": layer.name, "espesor_m": layer.thickness_m,
                         "k_w_mk": layer.conductivity_w_mk, "R_m2k_w": layer.resistance_m2k_w}
                        for layer in face.layers.layers_at(time_s)],
        })
        rows[label] = described
    return rows


def run(args, config, construction):
    if any(not math.isfinite(x) or x <= 0 for x in (args.hours, args.dt)):
        raise ValueError("Horas y dt deben ser positivos y finitos")
    series, metadata, start, weather_info = load_weather(config, args, args.hours)
    model = weather_3d.build_model(config, series, start, args.hours, args.coarsen)
    p = replace(model["p"], dt_s=args.dt)
    model["p"] = p
    concrete = model["grid"]["concrete"]
    soil = model["grid"]["soil"]
    reference = prepare(p)
    limit = min(reference.general_dt_s, reference.local_dt_s)
    places = weather_3d.locate_core_and_surface(model)
    material = np.where(concrete, weather_3d.MATERIAL["hormigon"],
                        np.where(soil, weather_3d.MATERIAL["suelo"], weather_3d.MATERIAL["aire"]))

    pours = [Pour(**row) for row in construction["pours"]]
    plan, plan_info = build_plan_on_concrete(model, pours)
    volume_check = check_plan_volume(plan, concrete, p.spacing_m, model["ifc_sha256"])
    hydration_cfg = construction["hydration"]
    thermal = construction["thermal"]
    hydration = ExponentialAdiabaticHydration(
        theta_inf_c=float(hydration_cfg["theta_inf_c"]),
        tau_h=float(hydration_cfg["tau_h"]),
        density_kg_m3=float(thermal["density_kg_m3"]),
        specific_heat_j_kgk=float(thermal["specific_heat_j_kgk"]),
    )
    ea = float(construction["kinetics"]["activation_energy_j_mol"])
    save_every = max(1, math.ceil(6.0 * HOUR / p.dt_s))
    initial_c = np.full(tuple(p.shape), float(config["soil"]["deep_temperature_c"]))
    result = solve_construction(p, plan, hydration, save_every=save_every,
                                activation_energy_j_mol=ea, source_mask=concrete, initial_c=initial_c)

    functions = series.boundary_functions(start)
    surface_zone = places["zone"] == weather_3d.ZONE["superficie"]
    probes = {"nucleo": places["core"], "sonda_superior": places["top"], "sonda_lateral": places["side"]}
    history = {key: [] for key in ("t_h", "aire_c", "tmax_c", "tmin_superficie_c", "delta_t_c",
                                   "nucleo_c", "sonda_superior_c", "sonda_lateral_c")}
    frame_rows = []
    tmax_record = None
    delta_record = None

    for index, (time_s, temperature, active, age) in enumerate(zip(
            result.time_s, result.temperature_c, result.active, result.equivalent_age_s)):
        metrics = frame_metrics(model, places, temperature, active)
        air = functions["air_c"](time_s)
        delta = (metrics["tmax_c"] - metrics["tmin_surface_c"]
                 if metrics["tmin_surface_c"] is not None else None)
        history["t_h"].append(float(time_s) / HOUR)
        history["aire_c"].append(float(air))
        history["tmax_c"].append(metrics["tmax_c"])
        history["tmin_superficie_c"].append(metrics["tmin_surface_c"])
        history["delta_t_c"].append(delta)
        for key, cell in probes.items():
            history[f"{key}_c"].append(float(temperature[cell]) if active[cell] else np.nan)
        frame_rows.append({
            "index": index, "t_h": float(time_s) / HOUR, **metrics,
            "delta_t_c": delta, "air_c": float(air),
            "equivalent_age_max_h": float(age[concrete].max()) / HOUR if np.any(concrete) else None,
        })
        if tmax_record is None or metrics["tmax_c"] > tmax_record["value_c"]:
            tmax_record = {"value_c": metrics["tmax_c"], "time_h": float(time_s) / HOUR,
                           "cell": list(metrics["tmax_cell"]), "xyz_m": metrics["tmax_xyz_m"],
                           "frame_index": index}
        if delta is not None and (delta_record is None or delta > delta_record["value_c"]):
            delta_record = {"value_c": float(delta), "time_h": float(time_s) / HOUR,
                            "tmax": {"value_c": metrics["tmax_c"], "cell": list(metrics["tmax_cell"]),
                                     "xyz_m": metrics["tmax_xyz_m"]},
                            "tmin_superficie": {"value_c": metrics["tmin_surface_c"],
                                                "cell": list(metrics["tmin_surface_cell"]),
                                                "xyz_m": metrics["tmin_surface_xyz_m"]},
                            "frame_index": index}

    name = Path(metadata["folder"]).name if metadata.get("folder") else "sintetico"
    out = Path(args.out) / name
    (out / "vtk").mkdir(parents=True, exist_ok=True)

    frames = []
    for row, time_s, temperature, active in zip(frame_rows, result.time_s, result.temperature_c, result.active):
        file_name = f"temperature_{row['index']:04d}.vti"
        write_vti(out / "vtk" / file_name,
                  fields(model, places, material, temperature, active),
                  p.spacing_m, model["origin_m"], {"TimeValue": float(time_s) / HOUR})
        frames.append((float(time_s) / HOUR, f"vtk/{file_name}"))
    write_pvd(out / "temperature.pvd", frames)

    last_t, last_temp, last_active = result.time_s[-1], result.temperature_c[-1], result.active[-1]
    write_vti(out / "final.vti", fields(model, places, material, last_temp, last_active),
              p.spacing_m, model["origin_m"], {"TimeValue": float(last_t) / HOUR})
    tmax_index = tmax_record["frame_index"]
    write_vti(out / "tmax.vti", fields(model, places, material, result.temperature_c[tmax_index],
                                       result.active[tmax_index]),
              p.spacing_m, model["origin_m"], {"TimeValue": float(result.time_s[tmax_index]) / HOUR})
    delta_index = delta_record["frame_index"] if delta_record is not None else tmax_index
    write_vti(out / "delta_tmax.vti", fields(model, places, material, result.temperature_c[delta_index],
                                             result.active[delta_index]),
              p.spacing_m, model["origin_m"], {"TimeValue": float(result.time_s[delta_index]) / HOUR})

    with (out / "serie_temporal.csv").open("w", newline="", encoding="utf-8") as stream:
        columns = list(history)
        writer = csv.writer(stream)
        writer.writerow(columns)
        for values in zip(*(history[key] for key in columns)):
            writer.writerow([f"{value:.6g}" for value in values])

    plot_hydration(out / "hidratacion.png", hydration)
    plot_weather(out / "clima_14d.png", series, metadata, start, args.hours, weather_info)
    plot_core_surface(out / "nucleo_superficie.png", history, metadata, start)

    slice_summary = {
        "core": {"cell": tmax_record["cell"], "xyz_m": tmax_record["xyz_m"]},
        "surface_probes": {"superior": {"cell": list(places["top"]), "xyz_m": cell_centre(model, places["top"])},
                           "lateral": {"cell": list(places["side"]), "xyz_m": cell_centre(model, places["side"])}},
        "weather": {"folder": metadata.get("folder")},
    }
    view_3d.matplotlib_slices(out / "tmax.vti", slice_summary, out / "slices_tmax.png")

    scale = max(1.0, float(np.max(np.abs(result.energy_j))),
                float(np.max(np.abs(result.placement_energy_j))))
    max_error = float(np.max(np.abs(result.energy_balance_error_j)))
    boundary_times = {"t0": 0.0}
    if args.hours >= 72.0:
        boundary_times["t_72h"] = 72.0 * HOUR
    core_vs = []
    for core_t, top_t, side_t in zip(history["nucleo_c"], history["sonda_superior_c"], history["sonda_lateral_c"]):
        if np.isfinite(core_t):
            available = [value for value in (top_t, side_t) if np.isfinite(value)]
            if available:
                core_vs.append(float(core_t - min(available)))

    summary = {
        "data_status": (
            "Clima: " + metadata.get("status", "serie") + ". Geometría: IFC voxelizado. "
            "Vertidas, hidratación exponencial, moldaje, manta y suelo: supuestos del curso/config. "
            "No es una recomendación de construcción ni una calibración experimental."
        ),
        "commit": git_commit(),
        "snapshot": {
            "folder": metadata.get("folder"),
            "kind": metadata.get("kind"),
            "status": metadata.get("status"),
            "retrieved_at": metadata.get("retrieved_at"),
            "sha256": metadata.get("sha256"),
            "request_url": metadata.get("request_url"),
            "first_time": metadata.get("first_time"),
            "last_time": metadata.get("last_time"),
        },
        "t0_utc": to_iso(start),
        "weather": weather_info,
        "simulation": {
            "hours": args.hours,
            "dt_s": float(p.dt_s),
            "dt_limit_s": float(limit),
            "dt_effective_limit_s": float(0.8 * limit),
            "dt_average_s": float(p.duration_s / result.step_count) if result.step_count else None,
            "save_every_steps": save_every,
            "saved_states": int(result.time_s.size),
            "max_saved_gap_h": (float(np.max(np.diff(result.time_s))) / HOUR
                                if result.time_s.size > 1 else None),
            "steps": int(result.step_count),
            "grid_cells": list(p.shape),
            "spacing_m": [float(v) for v in p.spacing_m],
            "coarsen": args.coarsen,
            "ifc_sha256": model["ifc_sha256"],
            "energy_balance_relative": max_error / scale,
            "energy_balance_max_abs_j": max_error,
            "energy_initial_j": float(result.energy_j[0]),
            "energy_final_j": float(result.energy_j[-1]),
            "boundary_heat_in_j": float(result.boundary_heat_in_j[-1]),
            "source_heat_in_j": float(result.source_heat_in_j[-1]),
            "placement_energy_j": float(result.placement_energy_j[-1]),
        },
        "boundaries": {
            "faces": {face_name: boundary_record(face, boundary_times)
                      for face_name, face in model["faces"].items()},
            "base": {"type": "Dirichlet", "temperature_c": float(config["soil"]["deep_temperature_c"]),
                     "source": config["soil"]["source"]},
            "formwork_strip_after_h": float(config["formwork"]["strip_after_h"]),
            "insulation_on_top_from_h": float(config["insulation"]["on_top_from_h"]),
        },
        "plan": {"pours": [dict(row, start_h=float(row["start_s"]) / HOUR) for row in plan.rows], **plan_info},
        "volume_check": volume_check,
        "hydration": {
            "model": "exponential_adiabatic",
            "theta_inf_c": float(hydration.theta_inf_c),
            "tau_h": float(hydration.tau_s / HOUR),
            "tau_s": float(hydration.tau_s),
            "duration_s": float(hydration.duration_s),
            "activation_energy_j_mol": ea,
            "density_kg_m3": float(hydration.density_kg_m3),
            "specific_heat_j_kgk": float(hydration.specific_heat_j_kgk),
            "q_at_age_zero_w_m3": float(hydration.rate(0.0)),
            "source": hydration_cfg.get("source"),
        },
        "tmax_concrete": {
            **tmax_record,
            "threshold_c": 70.0,
            "exceeds_70_c": bool(tmax_record["value_c"] > 70.0),
            "margin_to_70_c": float(70.0 - tmax_record["value_c"]),
        },
        "delta_t_max": {
            "definition": "ΔT(t) = Tmax_hormigón(t) − Tmin_superficie(t); superficie = hormigón ya colocado con zone = 2 (cara expuesta al aire).",
            "criterion_c": 20.0,
            "value_c": delta_record["value_c"] if delta_record else None,
            "time_h": delta_record["time_h"] if delta_record else None,
            "tmax": delta_record["tmax"] if delta_record else None,
            "tmin_superficie": delta_record["tmin_superficie"] if delta_record else None,
            "exceeds_20_c": bool(delta_record and delta_record["value_c"] > 20.0),
        },
        "core_vs_surface_probes": {
            "core": {"cell": list(places["core"]), "xyz_m": cell_centre(model, places["core"]),
                     "depth_to_boundary_m": float(places["core_depth_m"])},
            "probes": {"superior": {"cell": list(places["top"]), "xyz_m": cell_centre(model, places["top"])},
                       "lateral": {"cell": list(places["side"]), "xyz_m": cell_centre(model, places["side"])}},
            "max_core_minus_min_probe_c": max(core_vs) if core_vs else None,
            "note": "Dato secundario: núcleo geométrico menos la menor de las dos sondas superficiales.",
        },
        "files": {
            "summary": "resumen.json",
            "time_series": "serie_temporal.csv",
            "vtk_series": "temperature.pvd (cuadros en vtk/)",
            "vtk_final": "final.vti",
            "vtk_tmax": "tmax.vti",
            "vtk_delta_tmax": "delta_tmax.vti",
            "figures": ["hidratacion.png", "clima_14d.png", "nucleo_superficie.png", "slices_tmax.png"],
        },
        "tmax_by_frame": frame_rows,
    }
    (out / "resumen.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT_DIR / "config" / "environment_g8.json"))
    parser.add_argument("--construction", default=str(ROOT_DIR / "config" / "construction_g8.json"))
    parser.add_argument("--snapshot")
    parser.add_argument("--start")
    parser.add_argument("--hours", type=float, default=336.0)
    parser.add_argument("--dt", type=float, default=600.0)
    parser.add_argument("--coarsen", type=int, default=1)
    parser.add_argument("--synthetic", action="store_true", help="serie SINTÉTICA, solo para pruebas")
    parser.add_argument("--out", default=str(ROOT_DIR / "results" / "e12_14d"))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    construction = json.loads(Path(args.construction).read_text(encoding="utf-8"))
    out, summary = run(args, config, construction)
    s = summary["simulation"]
    t = summary["tmax_concrete"]
    d = summary["delta_t_max"]
    print(f"Resultados: {out}")
    print(f"Clima: {summary['snapshot']['folder']} | t0 {summary['t0_utc']} | "
          f"{summary['weather']['forecast_hours']} h pronóstico, {summary['weather']['tail_hours']} h relleno")
    print(f"Simulación: {s['hours']:g} h, dt = {s['dt_s']:g} s (límite {s['dt_limit_s']:.0f} s), "
          f"{s['steps']} pasos, balance {s['energy_balance_relative']:.2e}")
    v = summary["volume_check"]
    print(f"Volumen: {v['layers_volume_m3']:.3f} m³ en vertidas = {v['voxel_volume_m3']:.3f} m³ voxel; "
          f"IFC {v['ifc_volume_m3']:.3f} m³ (error {v['relative_error_vs_ifc']:.2%})")
    print(f"T máx hormigón: {t['value_c']:.2f} °C a {t['time_h']:.1f} h en {np.round(t['xyz_m'], 2).tolist()} m "
          f"(70 °C: {'supera' if t['exceeds_70_c'] else 'no supera'})")
    if d["value_c"] is not None:
        print(f"ΔT máx: {d['value_c']:.2f} °C a {d['time_h']:.1f} h (criterio 20 °C: "
              f"{'supera' if d['exceeds_20_c'] else 'no supera'})")


if __name__ == "__main__":
    main()
