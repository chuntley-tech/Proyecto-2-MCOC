"""Demo E10: condiciones de borde ambientales con insumos trazables.

Sección vertical 2D de la fundación (en la grilla 2D del solver el eje
vertical se llama «y»; aquí se dibuja como z) (mitad, por simetría en x = 0):

* hormigón 9 m × 3,3 m, colocado a 16 °C, con fuente de hidratación sintética;
* cara superior: manta aislante + sol (sol-aire) + viento (h = 5,7 + 3,8 v);
* costado: moldaje de terciado que se RETIRA a las 72 h (cambia R en el tiempo);
* suelo explícito debajo (2,2 m) y a un costado (1,5 m), con su superficie al aire;
* base del suelo a temperatura profunda (Dirichlet, supuesto declarado).

Clima: el último snapshot de data/weather/ descargado antes del momento de
decisión. Si no hay ninguno, usa una serie SINTÉTICA y lo dice en la figura.
Compara "desmolde a 72 h" con "moldaje permanente".

    python -m scripts.environment_demo
    python -m scripts.environment_demo --decision 2026-11-20T12:00Z --synthetic
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from environment import (Layer, LayerSchedule, Region, SoilModel, SurfaceExposure, SurfaceMap, add_soil_layer)
from thermal3d.construction import CosineHydration
from thermal3d.solver import Parameters, advance, prepare
from weather.series import HOUR, coverage, fill_tail, from_open_meteo, synthetic_series
from weather.snapshots import latest_before, load_snapshot

ROOT_DIR = Path(__file__).resolve().parents[1]


def load_weather(config, decision, synthetic=False):
    """Serie que cubre los 14 días + informe de qué es dato y qué es relleno."""
    construction = config["construction"]
    start, days = construction["start_utc"], construction["days_after_start"]
    root = ROOT_DIR / config["weather"]["snapshot_root"]
    site = config["site"]
    coordinates = (site["latitude"], site["longitude"])
    if not synthetic:
        try:
            folder = latest_before(decision, root=root, kind="forecast", coordinates=coordinates)
        except LookupError:
            folder = None
        if folder is not None:
            metadata, payload = load_snapshot(folder)
            series = from_open_meteo(payload, {**metadata, "folder": str(folder.relative_to(ROOT_DIR))})
            report = coverage(series, start, days)
            method = config["weather"]["tail_method"]
            reference = None
            archive_info = None
            if method in ("auto", "climatologia") and report["missing_hours_at_end"] > 0:
                try:
                    archive = latest_before(decision, root=root, kind="archive", coordinates=coordinates)
                except LookupError:
                    if method == "climatologia":
                        raise
                else:
                    meta_a, payload_a = load_snapshot(archive)
                    reference = from_open_meteo(payload_a, meta_a)
                    archive_info = {"folder": archive.relative_to(ROOT_DIR).as_posix(), "sha256": meta_a["sha256"]}
                    method = "climatologia"
            if method == "auto":
                method = "persistencia"
            filled = fill_tail(series, start, days, method=method, reference=reference)
            return filled, report, {"type": "snapshot", "folder": str(folder.relative_to(ROOT_DIR)),
                                    "retrieved_at": metadata["retrieved_at"], "sha256": metadata["sha256"],
                                    "status": metadata["status"], "tail_method": filled.snapshot.get("tail_method"),
                                    "climatology_reference": archive_info}
    series = synthetic_series(start, days)
    return series, coverage(series, start, days), {
        "type": "SINTETICO", "note": "No hay snapshot (o se pidió --synthetic): serie sintética, no es pronóstico."}


def build_case(config, weather, strip_formwork=True):
    section, soil_cfg, concrete = config["demo_section"], config["soil"], config["concrete"]
    dx, dz = section["spacing_m"]
    nx, nz = round(section["half_width_m"] / dx), round(section["height_m"] / dz)
    soil = SoilModel(**{k: soil_cfg[k] for k in ("depth_m", "margin_m", "conductivity_w_mk", "density_kg_m3",
                                                  "specific_heat_j_kgk", "deep_temperature_c")})
    grid = add_soil_layer(np.ones((nx, nz), bool), (dx, dz), (nx * dx, nz * dz),
                          {k: concrete[k] for k in ("conductivity_w_mk", "density_kg_m3", "specific_heat_j_kgk")},
                          soil)
    # La simetría está en x = 0: el margen de suelo solo va hacia x+.
    margin = round(soil.margin_m / dx)
    for key in ("active", "concrete", "soil", "conductivity_w_mk", "density_kg_m3", "specific_heat_j_kgk"):
        grid[key] = grid[key][margin:]
    shape = grid["active"].shape
    lengths = (shape[0] * dx, shape[1] * dz)

    start = config["construction"]["start_utc"]
    f = weather.boundary_functions(start)
    conv, solar = config["convection"], config["solar"]
    form, ins = config["formwork"], config["insulation"]
    formwork = Layer("moldaje terciado", form["thickness_m"], form["conductivity_w_mk"], form["source"])
    blanket = Layer("manta aislante", ins["thickness_m"], ins["conductivity_w_mk"], ins["source"])
    side_layers = (LayerSchedule.formwork_removed_at(form["strip_after_h"] * HOUR, formwork) if strip_formwork
                   else LayerSchedule(((0.0, (formwork,)),)))
    insulation_start = ins["on_top_from_h"] * HOUR
    top_stages = ((insulation_start, (blanket,)),)
    if insulation_start > 0:
        top_stages = ((0.0, ()),) + top_stages
    common = dict(air_c=f["air_c"], wind_10m_m_s=f["wind_10m_m_s"], shortwave_w_m2=f["shortwave_w_m2"],
                  max_wind_m_s=f["max_wind_m_s"], **{key: conv[key] for key in
                  ("wind_height_m", "wind_exponent", "h_a_w_m2k", "h_b_w_m2k_per_m_s")})
    top = SurfaceExposure(**common, layers=LayerSchedule(top_stages),
                          solar_absorptance=solar["absorptance_concrete"], solar_factor=solar["top_factor"],
                          name="cara superior (manta)")
    # Con moldaje el sol lo absorbe el terciado; sin moldaje, el hormigón. Se usa una absortancia media.
    side = SurfaceExposure(**common, layers=side_layers, solar_absorptance=solar["absorptance_formwork"],
                           solar_factor=solar["side_factor"], name="costado (moldaje)")
    ground = SurfaceExposure(**common, solar_absorptance=solar["absorptance_concrete"],
                             solar_factor=solar["top_factor"], name="superficie del suelo")
    exposed = SurfaceMap((Region(side, frozenset({"x+"}), grid["concrete"], "costado"),
                          Region(ground, frozenset({"y+"}), grid["soil"], "suelo")))
    p = Parameters(shape=shape, lengths_m=lengths, conductivity_w_mk=grid["conductivity_w_mk"],
                   density_kg_m3=grid["density_kg_m3"], specific_heat_j_kgk=grid["specific_heat_j_kgk"],
                   dt_s=section["dt_s"], duration_s=config["construction"]["days_after_start"] * 86400.0,
                   boundaries={"y+": top, "y-": grid["base"]}, active=grid["active"], exposed=exposed)
    initial = np.where(grid["concrete"], concrete["placement_c"], soil.deep_temperature_c)
    return p, initial, grid, {"top": top, "side": side, "ground": ground}


def run(p, initial, grid, concrete):
    c = prepare(p)
    if p.dt_s > min(c.general_dt_s, c.local_dt_s):
        raise ValueError(f"Δt = {p.dt_s} s inestable; límite {min(c.general_dt_s, c.local_dt_s):.0f} s")
    hydration = CosineHydration(concrete["qmax_w_m3"], concrete["hydration_duration_s"])
    temperature = initial.astype(float).copy()
    cap = c.capacity_j_k
    energy0 = float(np.sum(cap * temperature * c.active))
    nz_soil = int(np.argmax(grid["concrete"][0]))
    probes = {"núcleo (eje, media altura)": (0, nz_soil + (p.shape[1] - nz_soil) // 2),
              "costado, media altura": (int(np.where(grid["concrete"][:, -1])[0].max()),
                                        nz_soil + (p.shape[1] - nz_soil) // 2),
              "superficie superior (eje)": (0, p.shape[1] - 1),
              "base del hormigón (eje)": (0, nz_soil)}
    times, history = [0.0], {name: [temperature[ij]] for name, ij in probes.items()}
    concrete_max, gradient = [float(temperature[grid["concrete"]].max())], [0.0]
    q_boundary = q_source = 0.0
    steps = int(np.ceil(p.duration_s / p.dt_s))
    for step in range(steps):
        t = step * p.dt_s
        next_time = min((step + 1) * p.dt_s, p.duration_s)
        source = hydration.rate(t) * grid["concrete"]
        qb, qs = advance(p, c, temperature, t, next_time - t, source)
        q_boundary, q_source = q_boundary + qb, q_source + qs
        times.append(next_time)
        for name, ij in probes.items():
            history[name].append(float(temperature[ij]))
        values = temperature[grid["concrete"]]
        concrete_max.append(float(values.max()))
        gradient.append(float(values.max() - values.min()))
    energy = float(np.sum(cap * temperature * c.active))
    balance = (energy - energy0) - (q_boundary + q_source)
    return {"times_h": np.array(times) / HOUR, "probes": {k: np.array(v) for k, v in history.items()},
            "concrete_max_c": np.array(concrete_max), "concrete_spread_c": np.array(gradient),
            "final": temperature, "dt_limit_s": min(c.general_dt_s, c.local_dt_s),
            "energy_balance_rel": abs(balance) / max(abs(q_source), 1.0), "probe_cells": probes}


def plot(path, weather, report, origin_info, cases, grid, p, config):
    start = datetime.fromisoformat(config["construction"]["start_utc"].replace("Z", "+00:00")).timestamp()
    t_h = (weather.time_s - start) / HOUR
    keep = (t_h >= 0) & (t_h <= config["construction"]["days_after_start"] * 24)
    fig, axes = plt.subplots(3, 1, figsize=(11, 12), gridspec_kw={"height_ratios": [1, 1.3, 1.1]})
    ax = axes[0]
    ax.plot(t_h[keep], weather.air_c[keep], color="tab:blue", label="aire 2 m [°C]")
    ax.plot(t_h[keep], weather.wind_10m_m_s[keep], color="tab:green", label="viento 10 m [m/s]")
    ax2 = ax.twinx()
    ax2.fill_between(t_h[keep] - 0.5, weather.shortwave_w_m2[keep], color="gold", alpha=0.35, step="mid")
    ax2.set_ylabel("radiación de onda corta [W/m²]")
    origins = np.array(weather.origin)[keep]
    for name, colour in (("persistencia", "0.85"), ("climatologia", "0.8"), ("conservador", "0.75")):
        sel = origins == name
        if np.any(sel):
            ax.axvspan(t_h[keep][sel].min(), t_h[keep][sel].max(), color=colour, alpha=0.5, zorder=0,
                       label=f"cola completada: {name}")
    source = (f"snapshot {origin_info['folder']} (descargado {origin_info['retrieved_at']})"
              if origin_info["type"] == "snapshot" else "SERIE SINTÉTICA — no es pronóstico")
    ax.set_title(f"Clima usado: {source}\nLa serie de entrada cubre {report['covered_hours']:.0f} de "
                 f"{report['needed_hours']:.0f} h del período", fontsize=10)
    ax.set_xlabel("horas desde el inicio de la construcción")
    ax.legend(loc="upper right", fontsize=8)

    ax = axes[1]
    styles = {"núcleo (eje, media altura)": "tab:red", "costado, media altura": "tab:purple",
              "superficie superior (eje)": "tab:orange", "base del hormigón (eje)": "tab:brown"}
    for label, (result, line) in cases.items():
        for name, colour in styles.items():
            ax.plot(result["times_h"], result["probes"][name], color=colour, ls=line,
                    label=f"{name} — {label}" if line == "-" or "costado" in name else None)
    strip = config["formwork"]["strip_after_h"]
    ax.axvline(strip, color="k", lw=0.8, ls=":")
    ax.text(strip + 2, ax.get_ylim()[0] + 0.5, f"desmolde {strip} h", fontsize=8)
    ax.set_ylabel("temperatura [°C]")
    ax.set_xlabel("horas desde el inicio")
    ax.set_title(f"Hormigón: continuo = desmolde a {strip:g} h, segmentado = moldaje permanente", fontsize=10)
    ax.legend(fontsize=7, ncol=2)

    ax = axes[2]
    final = cases[f"desmolde {strip:g} h"][0]["final"]
    shown = np.where(grid["active"], final, np.nan).T
    dx, dz = p.spacing_m
    depth = config["soil"]["depth_m"]
    image = ax.imshow(shown, origin="lower", cmap="inferno", aspect="auto",
                      extent=(0, p.lengths_m[0], -depth, p.lengths_m[1] - depth))
    ax.contour(np.linspace(dx / 2, p.lengths_m[0] - dx / 2, p.shape[0]),
               np.linspace(-depth + dz / 2, p.lengths_m[1] - depth - dz / 2, p.shape[1]),
               grid["concrete"].T.astype(float), levels=[0.5], colors="w", linewidths=1)
    fig.colorbar(image, ax=ax, label="°C")
    ax.set_xlabel("x desde el eje [m]")
    ax.set_ylabel("z sobre el terreno [m]")
    ax.set_title(f"Temperatura a los {config['construction']['days_after_start']} días (desmolde {strip:g} h); "
                 "debajo de z = 0 es suelo", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT_DIR / "config" / "environment_g8.json"))
    parser.add_argument("--decision", help="momento de decisión UTC; usa el último snapshot anterior")
    parser.add_argument("--synthetic", action="store_true", help="ignorar snapshots y usar serie sintética")
    parser.add_argument("--out", default=str(ROOT_DIR / "results" / "environment"))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    decision = args.decision or config["weather"]["decision_time_utc"] or datetime.now(timezone.utc).isoformat()
    weather, report, origin_info = load_weather(config, decision, args.synthetic)

    cases = {}
    strip_hours = config["formwork"]["strip_after_h"]
    for label, strip, line in ((f"desmolde {strip_hours:g} h", True, "-"), ("moldaje permanente", False, "--")):
        p, initial, grid, faces = build_case(config, weather, strip)
        cases[label] = (run(p, initial, grid, config["concrete"]), line)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    plot(out / "environment_demo.png", weather, report, origin_info, cases, grid, p, config)
    strip_s = config["formwork"]["strip_after_h"] * HOUR
    side = faces["side"]
    summary = {
        "data_status": config["data_status"],
        "decision_time_utc": decision,
        "weather_source": origin_info,
        "coverage_of_weather_input": report,
        "weather_used": weather.summary(),
        "boundary_example_side_face": {"antes_desmolde": side.describe(strip_s - 1),
                                       "despues_desmolde": side.describe(strip_s + 1)},
        "grid": {"shape": list(p.shape), "spacing_m": list(p.spacing_m), "dt_s": p.dt_s},
        "results": {label: {"dt_limit_s": r["dt_limit_s"], "energy_balance_rel": r["energy_balance_rel"],
                            "concrete_max_c": float(r["concrete_max_c"].max()),
                            "max_internal_spread_c": float(r["concrete_spread_c"].max()),
                            "side_mid_c_at_96h": float(np.interp(96, r["times_h"], r["probes"]["costado, media altura"])),
                            "core_c_at_96h": float(np.interp(96, r["times_h"], r["probes"]["núcleo (eje, media altura)"]))}
                    for label, (r, _) in cases.items()},
    }
    (out / "environment_demo.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float) + "\n",
                                               encoding="utf-8")
    weather_rows = weather.to_rows()
    with open(out / "weather_used.csv", "w", encoding="utf-8") as handle:
        handle.write("time_utc,air_c,wind_10m_m_s,shortwave_w_m2,origin\n")
        for row in weather_rows:
            handle.write(f"{row['time_utc']},{row['air_c']:.2f},{row['wind_10m_m_s']:.2f},"
                         f"{row['shortwave_w_m2']:.1f},{row['origin']}\n")
    print(f"Clima: {origin_info['type']} {origin_info.get('folder', '')}")
    print(f"Cobertura de la serie de entrada: {report['covered_hours']:.0f}/{report['needed_hours']:.0f} h; "
          f"horas por origen: {weather.summary()['origin_hours']}")
    for label, data in summary["results"].items():
        print(f"{label}: Tmax {data['concrete_max_c']:.1f} °C, diferencia interna máx {data['max_internal_spread_c']:.1f} °C, "
              f"costado a 96 h {data['side_mid_c_at_96h']:.1f} °C, balance {data['energy_balance_rel']:.1e}")
    print(f"Figura y resumen en {out}")


if __name__ == "__main__":
    main()
