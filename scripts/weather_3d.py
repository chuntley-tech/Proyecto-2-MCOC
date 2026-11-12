"""E11: snapshot meteorológico real → condiciones de borde → simulación 3D corta → VTK.

Pasos (cada uno deja un archivo que se puede mostrar en el laboratorio):

1. Elige el snapshot (el último en data/weather/, o --snapshot) y comprueba su sha256.
2. Muestra la metadata y grafica temperatura del aire, viento y radiación.
3. Arma los bordes ambientales con ESA serie (aire, viento, sol, moldaje, manta, suelo).
4. Corre una simulación 3D corta sobre la fundación voxelizada desde el IFC.
5. Exporta .vti + .pvd (ParaView/PyVista) con temperatura, material, zona y profundidad.
6. Identifica núcleo y superficie y grafica sus trayectorias.

    python -m scripts.fetch_weather                         # primero: snapshot real (internet)
    python -m scripts.weather_3d                            # último snapshot, 48 h
    python -m scripts.weather_3d --hours 72 --every 6
    python -m scripts.weather_3d --snapshot data/weather/2026-11-11T1500Z_forecast
    python -m scripts.weather_3d --synthetic                # SOLO pruebas: serie sintética rotulada

El período simulado empieza en la primera hora del pronóstico posterior a la
descarga (o en la primera hora de un reanálisis) y no se extrapola: si la serie no
alcanza, el script se detiene en vez de inventar clima.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from environment import Layer, LayerSchedule, Region, SoilModel, SurfaceExposure, SurfaceMap, add_soil_layer
from scripts.voxelize_foundation import case_ifc
from thermal3d.construction import CosineHydration
from thermal3d.solver import Parameters, advance, prepare
from thermal3d.vtk_export import write_pvd, write_vti
from thermal3d.voxel import load_ifc_meshes, voxelize
from weather.series import HOUR, from_open_meteo, synthetic_series, to_epoch, to_iso
from weather.snapshots import list_snapshots, load_snapshot

ROOT_DIR = Path(__file__).resolve().parents[1]
MATERIAL = {"aire": 0, "hormigon": 1, "suelo": 2}
ZONE = {"fuera": 0, "interior": 1, "superficie": 2, "nucleo": 3, "contacto_suelo": 4}


# ---------------------------------------------------------------------------------------------- clima
def choose_snapshot(root, site, folder=None):
    if folder:
        return Path(folder)
    rows = [row for row in list_snapshots(root, "forecast")
            if all(row.get(key) == site[key] for key in ("latitude", "longitude"))]
    if not rows:
        raise LookupError(f"No hay snapshots en {root}. Ejecute primero: python -m scripts.fetch_weather")
    return Path(rows[-1]["folder"])


def load_weather(args, config):
    if args.synthetic:
        start = args.start or config["construction"]["start_utc"]
        series = synthetic_series(start, args.hours / 24 + 1)
        meta = {"kind": "sintetico", "status": "SERIE SINTÉTICA, no es pronóstico ni dato",
                "retrieved_at": None, "sha256": None, "folder": None, "units": {}}
        return series, meta, to_epoch(start)
    site = config["site"]
    folder = choose_snapshot(ROOT_DIR / config["weather"]["snapshot_root"], site, args.snapshot)
    metadata, payload = load_snapshot(folder)                 # falla si el hash no coincide
    if metadata["kind"] not in ("forecast", "archive", "historical_forecast"):
        raise ValueError("E11 requiere un pronóstico determinista o un histórico")
    if any(metadata.get(key) != site[key] for key in ("latitude", "longitude")):
        raise ValueError("El snapshot no corresponde al punto meteorológico configurado para G8")
    try:
        shown = str(folder.resolve().relative_to(ROOT_DIR))
    except ValueError:
        shown = folder.name
    metadata = {**metadata, "folder": shown}
    series = from_open_meteo(payload, metadata)
    if args.start:
        start = to_epoch(args.start)
    elif metadata["kind"] == "forecast":
        # Primera hora completa después de la descarga: lo que efectivamente era pronóstico.
        start = math.ceil(to_epoch(metadata["retrieved_at"]) / HOUR) * HOUR
    else:
        start = series.start_s
    return series, metadata, start


def plot_weather(path, series, metadata, start, hours):
    t = (series.time_s - start) / HOUR
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout="constrained")
    axes[0].plot(t, series.air_c, color="tab:blue")
    axes[0].set_ylabel("aire 2 m [°C]\ntemperature_2m")
    axes[1].plot(t, series.wind_10m_m_s, color="tab:green")
    axes[1].set_ylabel("viento 10 m [m/s]\nwind_speed_10m")
    axes[2].step(t, series.shortwave_w_m2, where="pre", color="goldenrod")
    axes[2].set_ylabel("onda corta [W/m²]\nmedia hora anterior")
    axes[2].set_xlabel("horas desde el inicio de la simulación (t = 0)")
    for ax in axes:
        ax.axvspan(0, hours, color="tab:red", alpha=0.08, label="período simulado")
        ax.grid(alpha=0.3)
    axes[0].legend(loc="upper right", fontsize=8)
    source = metadata.get("folder") or "SERIE SINTÉTICA"
    axes[0].set_title(f"{metadata['status']} — {source}\n"
                      f"descargado {metadata.get('retrieved_at')}  ·  t = 0 en {to_iso(start)}  ·  "
                      f"sha256 {str(metadata.get('sha256'))[:12]}…", fontsize=9)
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ------------------------------------------------------------------------------------------ geometría
def load_voxels(coarsen=1):
    """Voxeliza el IFC vigente a la resolución solicitada y registra su hash."""
    path, guids = case_ifc(ROOT_DIR / "config" / "case_g8.json")
    meshes, source = load_ifc_meshes(path, guids)
    grid = voxelize(meshes, np.array([0.25, 0.25, 0.275]) * coarsen, source)
    return grid.component, grid.spacing_m, grid.origin_m, source["sha256"]


def surface_depth(concrete, exposed, spacing):
    """Distancia [m] por dentro del hormigón hasta la celda expuesta más cercana (6 vecinos)."""
    depth = np.where(exposed, 0.0, np.inf)
    depth[~concrete] = np.inf
    for _ in range(sum(concrete.shape)):
        before = depth.copy()
        for axis, step in enumerate(spacing):
            for shift in (1, -1):
                moved = np.roll(depth, shift, axis=axis)
                edge = [slice(None)] * 3
                edge[axis] = 0 if shift == 1 else -1
                moved[tuple(edge)] = np.inf
                depth = np.minimum(depth, np.where(concrete, moved + step, np.inf))
        if np.array_equal(depth, before):
            break
    return depth


def touching(concrete, other, *, exterior=True):
    """Celdas de hormigón con al menos una cara contra `other` (el borde de la caja cuenta como aire)."""
    result = np.zeros_like(concrete)
    for axis in range(3):
        for shift in (1, -1):
            neighbour = np.roll(other, shift, axis=axis)
            edge = [slice(None)] * 3
            edge[axis] = 0 if shift == 1 else -1
            neighbour[tuple(edge)] = exterior
            result |= concrete & neighbour
    return result


# ------------------------------------------------------------------------------------------- modelo
def build_model(config, series, start, hours, coarsen=1):
    component, spacing, origin, ifc_sha = load_voxels(coarsen)
    soil_cfg, concrete_cfg = config["soil"], config["concrete"]
    soil = SoilModel(depth_m=round(soil_cfg["depth_m"] / spacing[2]) * spacing[2],
                     margin_m=round(soil_cfg["margin_m"] / spacing[0]) * spacing[0],
                     **{k: soil_cfg[k] for k in ("conductivity_w_mk", "density_kg_m3", "specific_heat_j_kgk",
                                                  "deep_temperature_c")})
    material = {k: concrete_cfg[k] for k in ("conductivity_w_mk", "density_kg_m3", "specific_heat_j_kgk")}
    lengths = tuple(float(n * d) for n, d in zip(component.shape, spacing))
    grid = add_soil_layer(component > 0, spacing, lengths, material, soil)
    pads = [(int(round(-s / d)), 0) for s, d in zip(grid["origin_shift_m"], spacing)]
    comp = np.pad(component, [(p[0], grid["shape"][a] - component.shape[a] - p[0]) for a, p in enumerate(pads)])

    f = series.boundary_functions(start)
    end = hours * HOUR
    for name in ("air_c", "wind_10m_m_s"):
        f[name](0.0), f[name](end)                       # error claro si la serie no cubre el período
    window = (series.time_s >= start - HOUR) & (series.time_s <= start + end + HOUR)
    max_wind = float(np.max(series.wind_10m_m_s[window]))
    conv, solar = config["convection"], config["solar"]
    form, ins = config["formwork"], config["insulation"]
    formwork = Layer("moldaje terciado", form["thickness_m"], form["conductivity_w_mk"])
    blanket = Layer("manta aislante", ins["thickness_m"], ins["conductivity_w_mk"])
    common = dict(air_c=f["air_c"], wind_10m_m_s=f["wind_10m_m_s"], shortwave_w_m2=f["shortwave_w_m2"],
                  max_wind_m_s=max_wind, wind_height_m=conv["wind_height_m"], wind_exponent=conv["wind_exponent"],
                  h_a_w_m2k=conv["h_a_w_m2k"], h_b_w_m2k_per_m_s=conv["h_b_w_m2k_per_m_s"])
    side = SurfaceExposure(**common, name="costados (moldaje)",
                           layers=LayerSchedule.formwork_removed_at(form["strip_after_h"] * HOUR, formwork),
                           solar_absorptance=solar["absorptance_formwork"], solar_factor=solar["side_factor"])
    insulation_start = ins["on_top_from_h"] * HOUR
    insulation = ((0.0, ()),) if insulation_start > 0 else ()
    top = SurfaceExposure(**common, name="caras superiores (manta)",
                          layers=LayerSchedule(insulation + ((insulation_start, (blanket,)),)),
                          solar_absorptance=solar["absorptance_concrete"], solar_factor=solar["top_factor"])
    ground = SurfaceExposure(**common, name="terreno descubierto", solar_absorptance=solar["absorptance_concrete"],
                             solar_factor=solar["top_factor"])
    concrete, soil_mask = grid["concrete"], grid["soil"]
    exposed = SurfaceMap((Region(side, frozenset({"x-", "x+", "y-", "y+"}), concrete, "costados"),
                          Region(top, frozenset({"z+"}), concrete, "superior"),
                          Region(ground, frozenset({"z+"}), soil_mask, "terreno")))
    p = Parameters(shape=grid["shape"], lengths_m=grid["lengths_m"], conductivity_w_mk=grid["conductivity_w_mk"],
                   density_kg_m3=grid["density_kg_m3"], specific_heat_j_kgk=grid["specific_heat_j_kgk"],
                   dt_s=60.0, duration_s=end, boundaries={key: exposed for key in ("x-", "x+", "y-", "y+", "z+")}
                   | {"z-": grid["base"]},
                   active=grid["active"], exposed=exposed)
    origin_global = origin + np.asarray(grid["origin_shift_m"])
    return {"p": p, "grid": grid, "component": comp, "faces": {"side": side, "top": top, "ground": ground},
            "origin_m": origin_global, "ifc_sha256": ifc_sha, "spacing_m": spacing}


def locate_core_and_surface(model):
    grid, p = model["grid"], model["p"]
    concrete = grid["concrete"]
    exposed = touching(concrete, ~grid["active"])             # cara al aire: recibe clima, moldaje o manta
    on_soil = touching(concrete, grid["soil"], exterior=False) & ~exposed
    # Núcleo geométrico: lo más alejado de TODO borde del hormigón (aire y suelo extraen calor).
    depth = surface_depth(concrete, exposed | on_soil, p.spacing_m)
    finite = np.where(concrete, depth, -1.0)
    deepest = np.argwhere(finite >= finite.max() - 1e-9)
    centre = np.argwhere(concrete).mean(axis=0)
    core = tuple(int(v) for v in deepest[np.argmin(np.linalg.norm(deepest - centre, axis=1))])
    column = np.flatnonzero(concrete[core[0], core[1], :])
    top = (core[0], core[1], int(column.max()))
    row = np.flatnonzero(concrete[:, core[1], core[2]])
    side = (int(row.max()), core[1], core[2])
    zone = np.where(concrete, ZONE["interior"], ZONE["fuera"]).astype(np.int8)
    zone[on_soil] = ZONE["contacto_suelo"]
    zone[exposed] = ZONE["superficie"]
    zone[core] = ZONE["nucleo"]
    return {"core": core, "top": top, "side": side, "zone": zone,
            "depth_m": np.where(concrete, depth, np.nan), "core_depth_m": float(depth[core])}


def cell_centre(model, index):
    return [float(o + (i + 0.5) * d) for o, i, d in zip(model["origin_m"], index, model["p"].spacing_m)]


# ------------------------------------------------------------------------------------------- cálculo
def run(args, config):
    if any(not math.isfinite(x) or x <= 0 for x in (args.hours, args.every, args.max_dt)):
        raise ValueError("Horas, intervalo de salida y paso máximo deben ser positivos y finitos")
    if not 1 <= args.coarsen <= 4:
        raise ValueError("Use un factor de malla entre 1 y 4")
    series, metadata, start = load_weather(args, config)
    model = build_model(config, series, start, args.hours, args.coarsen)
    out = Path(args.out) / (Path(metadata["folder"]).name if metadata.get("folder") else "sintetico")
    (out / "vtk").mkdir(parents=True, exist_ok=True)
    plot_weather(out / "clima_snapshot.png", series, metadata, start, args.hours)

    p, grid = model["p"], model["grid"]
    c = prepare(p)
    limit = min(c.general_dt_s, c.local_dt_s)
    every = args.every * HOUR
    dt = every / math.ceil(every / min(0.9 * limit, args.max_dt))
    places = locate_core_and_surface(model)
    concrete = grid["concrete"]
    material = np.where(concrete, MATERIAL["hormigon"], np.where(grid["soil"], MATERIAL["suelo"], MATERIAL["aire"]))
    hydration = CosineHydration(config["concrete"]["qmax_w_m3"], config["concrete"]["hydration_duration_s"])
    source_mask = concrete.astype(float) * (0.0 if args.no_hydration else 1.0)

    temperature = np.where(concrete, config["concrete"]["placement_c"], config["soil"]["deep_temperature_c"])
    temperature = np.where(grid["active"], temperature, np.nan).astype(float)
    work = np.nan_to_num(temperature)
    capacity = c.capacity_j_k
    energy0 = float(np.sum(capacity * work * grid["active"]))
    q_boundary = q_source = 0.0
    probes = {"núcleo": places["core"], "superficie superior": places["top"], "superficie lateral": places["side"]}
    history = {"t_h": [0.0], "aire_c": [series.boundary_functions(to_iso(start))["air_c"](0.0)],
               **{name: [float(work[idx])] for name, idx in probes.items()}, "tmax_c": [float(work[concrete].max())]}
    frames, tmax_where = [], []
    web_frames = []

    def fields():
        return {"temperature": np.where(grid["active"], work, np.nan).astype(np.float32),
                "material": material.astype(np.int8), "component_ifc": model["component"].astype(np.int16),
                "zone": places["zone"], "depth_to_boundary_m": places["depth_m"].astype(np.float32)}

    def save_frame(time_s, number):
        name = f"temperature_{number:04d}.vti"
        write_vti(out / "vtk" / name, fields(), p.spacing_m, model["origin_m"], {"TimeValue": time_s / HOUR})
        frames.append((time_s / HOUR, f"vtk/{name}"))
        web_frames.append(np.round(work[grid["active"]], 3).tolist())
        hot = np.unravel_index(np.nanargmax(np.where(concrete, work, -np.inf)), work.shape)
        tmax_where.append({"t_h": time_s / HOUR, "tmax_c": float(work[hot]), "cell": [int(v) for v in hot],
                           "xyz_m": cell_centre(model, hot), "depth_to_boundary_m": float(places["depth_m"][hot])})

    functions = series.boundary_functions(start)
    save_frame(0.0, 0)
    per_frame = int(round(every / dt))
    steps = math.ceil(p.duration_s / dt)
    if (steps - 1) * dt >= p.duration_s:
        steps -= 1
    for step in range(1, steps + 1):
        t = (step - 1) * dt
        end = min(step * dt, p.duration_s)
        qb, qs = advance(p, c, work, t, end - t, hydration.rate(t) * source_mask)
        q_boundary, q_source = q_boundary + qb, q_source + qs
        if step % max(1, per_frame // 6) == 0 or step == steps:
            history["t_h"].append(end / HOUR)
            history["aire_c"].append(functions["air_c"](end))
            for name, idx in probes.items():
                history[name].append(float(work[idx]))
            history["tmax_c"].append(float(work[concrete].max()))
        if step % per_frame == 0 or step == steps:
            save_frame(end, len(frames))
    write_pvd(out / "temperature.pvd", frames)
    # Último cuadro también fuera de vtk/: es el que queda en el repositorio (la serie se regenera).
    write_vti(out / "final.vti", fields(), p.spacing_m, model["origin_m"], {"TimeValue": args.hours})
    energy = float(np.sum(capacity * work * grid["active"]))
    balance = abs((energy - energy0) - (q_boundary + q_source)) / max(abs(q_source) + abs(q_boundary), 1.0)

    plot_trajectories(out / "nucleo_superficie.png", history, metadata, start)
    summary = {
        "data_status": ("Clima: " + metadata["status"] + ". Geometría: IFC voxelizado. Hidratación, moldaje, manta "
                        "y suelo: supuestos/sintéticos de config/environment_g8.json. Todo el volumen se coloca en "
                        "t = 0 (simulación corta de laboratorio, no el plan de vertidas)."),
        "weather": {key: metadata.get(key) for key in ("folder", "kind", "status", "model", "retrieved_at", "sha256",
                                                        "request_url", "latitude", "longitude", "grid_latitude",
                                                        "grid_longitude", "timezone", "units", "first_time",
                                                        "last_time")},
        "simulation": {"start_utc": to_iso(start), "hours": args.hours, "dt_s": dt, "dt_limit_s": limit,
                       "steps": steps, "grid_cells": list(p.shape), "spacing_m": [float(v) for v in p.spacing_m],
                       "coarsen": args.coarsen, "hydration": not args.no_hydration,
                       "energy_balance_relative": balance, "ifc_sha256": model["ifc_sha256"]},
        "boundaries_at_t0": {name: face.describe(0.0) for name, face in model["faces"].items()},
        "core": {"cell": list(places["core"]), "xyz_m": cell_centre(model, places["core"]),
                 "depth_to_boundary_m": places["core_depth_m"],
                 "definition": "celda de hormigón más alejada de todo borde (aire o suelo): núcleo geométrico. El núcleo térmico (T máx) se informa por cuadro en tmax_by_frame."},
        "surface_probes": {"superior": {"cell": list(places["top"]), "xyz_m": cell_centre(model, places["top"])},
                           "lateral": {"cell": list(places["side"]), "xyz_m": cell_centre(model, places["side"])}},
        "tmax_by_frame": tmax_where,
        "final": {name: history[name][-1] for name in ("núcleo", "superficie superior", "superficie lateral", "tmax_c")},
        "max_core_minus_surface_c": float(np.max(np.array(history["núcleo"]) -
                                                 np.minimum(history["superficie superior"], history["superficie lateral"]))),
        "files": {"vtk_series": "temperature.pvd (cuadros en vtk/, no versionados)", "vtk_final": "final.vti", "weather_plot": "clima_snapshot.png",
                  "dashboard": "visor_e11.json",
                  "trajectories": "nucleo_superficie.png"},
    }
    (out / "resumen.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    viewer = {
        "format": "mcoc-e11-v1", "summary": summary, "shape": p.shape,
        "spacing_m": p.spacing_m.tolist(), "origin_m": model["origin_m"].tolist(),
        "active_indices": np.flatnonzero(grid["active"]).tolist(),
        "material": material[grid["active"]].tolist(),
        "times_h": [time for time, _ in frames], "frames_c": web_frames,
        "history": history,
        "wind_m_s": [functions["wind_10m_m_s"](time * HOUR) for time in history["t_h"]],
        "solar_w_m2": [functions["shortwave_w_m2"](time * HOUR) for time in history["t_h"]],
    }
    with (out / "visor_e11.json").open("w", encoding="utf-8") as stream:
        json.dump(viewer, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    with open(out / "trayectorias.csv", "w", encoding="utf-8") as stream:
        names = list(history)
        stream.write(",".join(names) + "\n")
        for row in zip(*(history[n] for n in names)):
            stream.write(",".join(f"{v:.4f}" for v in row) + "\n")
    return out, summary


def plot_trajectories(path, history, metadata, start):
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    ax.plot(history["t_h"], history["aire_c"], color="tab:blue", lw=1, label="aire (snapshot)")
    colours = {"núcleo": "tab:red", "superficie superior": "tab:orange", "superficie lateral": "tab:purple"}
    for name, colour in colours.items():
        ax.plot(history["t_h"], history[name], color=colour, label=name)
    ax.plot(history["t_h"], history["tmax_c"], color="k", ls=":", label="T máx del hormigón")
    ax.set(xlabel="horas desde t = 0", ylabel="temperatura [°C]",
           title=f"Núcleo vs superficie — clima: {metadata.get('folder') or 'SINTÉTICO'} (t = 0 en {to_iso(start)})")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT_DIR / "config" / "environment_g8.json"))
    parser.add_argument("--snapshot", help="carpeta del snapshot; por defecto el último descargado")
    parser.add_argument("--start", help="inicio UTC (ISO); por defecto la primera hora pronosticada")
    parser.add_argument("--hours", type=float, default=48.0)
    parser.add_argument("--every", type=float, default=6.0, help="horas entre archivos VTK")
    parser.add_argument("--max-dt", type=float, default=900.0)
    parser.add_argument("--coarsen", type=int, default=1, help="2 = voxeles de 0,5 m (vista rápida)")
    parser.add_argument("--no-hydration", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="serie SINTÉTICA, solo para probar sin snapshot")
    parser.add_argument("--out", default=str(ROOT_DIR / "results" / "weather_3d"))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out, summary = run(args, config)
    w, s = summary["weather"], summary["simulation"]
    print(f"Clima: {w['status']} | {w['folder'] or 'sintético'} | descargado {w['retrieved_at']}")
    print(f"Simulación: {s['hours']:g} h desde {s['start_utc']}, dt = {s['dt_s']:.0f} s (límite {s['dt_limit_s']:.0f} s), "
          f"grilla {s['grid_cells']}, balance de energía {s['energy_balance_relative']:.1e}")
    core = summary["core"]
    print(f"Núcleo: celda {core['cell']} en {np.round(core['xyz_m'], 2).tolist()} m, a {core['depth_to_boundary_m']:.2f} m del borde más cercano")
    final = summary["final"]
    print(f"Al final: núcleo {final['núcleo']:.1f} °C, superficie superior {final['superficie superior']:.1f} °C, "
          f"lateral {final['superficie lateral']:.1f} °C; diferencial máximo {summary['max_core_minus_surface_c']:.1f} °C")
    print(f"Archivos en {out} (abrir temperature.pvd en ParaView o: python -m scripts.view_3d {out})")


if __name__ == "__main__":
    main()
