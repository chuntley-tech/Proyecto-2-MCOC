"""Casos del visor HTML: adapta entradas al solver propio, sin alterar archivos.

Cada respuesta conserva parámetros usados, origen IFC, unidades y tiempos
guardados. Los campos enviados al navegador se redondean a cinco decimales
solo para visualización; estadísticas y balances se calculan con float64.
"""

from dataclasses import replace
from functools import lru_cache
import hashlib
import math
import json
from pathlib import Path

import numpy as np

from environment import Layer, LayerSchedule, Region, SurfaceExposure, SurfaceMap
from scripts.voxelize_foundation import case_ifc
from thermal1d.solver import (Dirichlet, Neumann, Robin, Parameters as Parameters1D,
                              energy_per_area_j_m2, solve as solve1d)
from thermal3d import Parameters, prepare, solve
from thermal3d.reference import sine_initial
from thermal3d.solver import effective_h
from thermal3d.voxel import load_ifc_meshes, voxelize
from weather.series import HOUR, synthetic_series

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/"config/case_g8.json"
DEFAULTS = {"mode": "fundacion", "initial_c": 30.0, "profile": "uniforme", "amplitude_c": 0.0,
            "duration_days": 7.0, "conductivity_w_mk": 2.2, "density_kg_m3": 2400.0,
            "specific_heat_j_kgk": 900.0, "resolution_m": 0.25, "nodes": 32,
            "length_x_m": 1.0, "length_y_m": 1.0, "length_z_m": 1.0,
            "boundary_type": "robin", "boundary_c": 10.0, "h_w_m2k": 10.0,
            "flux_in_w_m2": 0.0, "resistance_m2k_w": 0.0,
            "bottom_type": "neumann", "bottom_c": 20.0, "bottom_h_w_m2k": 10.0,
            "bottom_flux_in_w_m2": 0.0, "source_w_m3": 0.0, "source_type": "constant",
            "qmax_w_m3": 1300.0, "source_duration_days": 2.0, "dt_s": None}
DEFAULTS.update({"foundation_geometry": "ifc", "foundation_x_m": 18.0,
                 "foundation_y_m": 18.0, "foundation_height_m": 3.3, "pour_count": 3})
DEFAULTS.update({"construction_mode": "simultaneous", "pour_schedule": ""})
DEFAULTS["activation_energy_j_mol"] = 33500.0
ENV_CHOICES = {
    "environment_mode": ("standard", "e10"),
    "environment_wind": ("fixed", "synthetic"),
    "environment_solar": ("off", "synthetic"),
    "environment_formwork": ("none", "permanent", "scheduled"),
    "environment_insulation": ("none", "blanket"),
    "environment_soil": ("standard", "equivalent"),
}
DEFAULTS.update({key: choices[0] for key, choices in ENV_CHOICES.items()})
DEFAULTS["environment_strip_h"] = 72.0
DEFAULTS["environment_h"] = 10.0
BOUNDS = {"initial_c": (-50, 150), "amplitude_c": (0, 100), "duration_days": (0.001, 30),
          "conductivity_w_mk": (0.05, 10), "density_kg_m3": (100, 5000),
          "specific_heat_j_kgk": (100, 5000), "resolution_m": (0.2, 1.0),
          "length_x_m": (0.1, 20), "length_y_m": (0.1, 20), "length_z_m": (0.1, 20),
          "boundary_c": (-50, 150), "h_w_m2k": (0, 1000), "flux_in_w_m2": (-5000, 5000),
          "resistance_m2k_w": (0, 5), "bottom_c": (-50, 150), "bottom_h_w_m2k": (0, 1000),
          "bottom_flux_in_w_m2": (-5000, 5000), "source_w_m3": (-2000, 5000),
          "qmax_w_m3": (0, 10000), "source_duration_days": (0.001, 30)}
BOUNDS.update({"foundation_x_m": (4, 40), "foundation_y_m": (4, 40),
               "foundation_height_m": (0.6, 12)})
BOUNDS["activation_energy_j_mol"] = (0, 100000)
BOUNDS["environment_strip_h"] = (0.01, 720)
BOUNDS["environment_h"] = (0.01, 1000)


def validate_options(data):
    """Lista cerrada de parámetros y límites para mantener la sesión interactiva."""
    if not isinstance(data, dict) or set(data)-set(DEFAULTS):
        raise ValueError("La solicitud contiene parámetros desconocidos")
    options = {**DEFAULTS, **data}
    if any(options[key] not in choices for key, choices in ENV_CHOICES.items()):
        raise ValueError("Opción ambiental E10 desconocida")
    if options["environment_mode"] == "e10" and options["mode"] != "fundacion":
        raise ValueError("El entorno E10 solo está disponible para la fundación")
    if options["construction_mode"] not in ("simultaneous", "staged"):
        raise ValueError("Modo constructivo desconocido")
    if options["mode"] not in ("fundacion", "1d", "2d", "3d"):
        raise ValueError("Caso desconocido")
    if options["profile"] not in ("uniforme", "seno"):
        raise ValueError("Perfil inicial desconocido")
    if options["source_type"] not in ("constant", "cosine"):
        raise ValueError("Fuente desconocida")
    if options["foundation_geometry"] not in ("ifc", "scaled"):
        raise ValueError("Geometría de fundación desconocida")
    if isinstance(options["pour_count"],bool) or not isinstance(options["pour_count"],int) or not 1 <= options["pour_count"] <= 12:
        raise ValueError("Cantidad de vertidas: entero entre 1 y 12")
    if options["boundary_type"] not in ("dirichlet", "neumann", "robin") or options["bottom_type"] not in ("dirichlet", "neumann", "robin"):
        raise ValueError("Condición de borde desconocida")
    for name, (low, high) in BOUNDS.items():
        value = options[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name}: use un valor entre {low:g} y {high:g}")
        options[name] = float(value)
    maximum = 401 if options["mode"] == "1d" else 48
    nodes = options["nodes"]
    if isinstance(nodes, bool) or not isinstance(nodes, int) or not 8 <= nodes <= maximum:
        raise ValueError(f"Número de nodos/celdas por eje: entero entre 8 y {maximum}")
    dt = options["dt_s"]
    if dt is not None and (isinstance(dt, bool) or not isinstance(dt, (float, int)) or not math.isfinite(dt) or dt <= 0):
        raise ValueError("Δt debe ser positivo o automático")
    schedule_for(options)
    return options


def schedule_for(options):
    """Cronograma explícito del visor: días y °C por capa de igual altura."""
    try:
        rows = json.loads(options["pour_schedule"]) if options["pour_schedule"] else [
            {"start_days": i, "placement_c": options["initial_c"]} for i in range(options["pour_count"])]
        if not isinstance(rows, list) or len(rows) != options["pour_count"]:
            raise ValueError()
        previous = 0
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"start_days", "placement_c"}:
                raise ValueError()
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in row.values()):
                raise ValueError()
            if not previous <= row["start_days"] <= 30 or not -50 <= row["placement_c"] <= 150:
                raise ValueError()
            previous = row["start_days"]
        return rows
    except (ValueError, TypeError):
        raise ValueError("Cronograma inválido: una fila por vertida, inicios ordenados de 0 a 30 días y temperaturas entre -50 y 150 °C") from None


def source_value(options, time_s):
    """Fuente volumétrica sintética de la pizarra [W/m³], evaluada en t_n [s].

    Qmax es potencia por volumen, no temperatura ni energía acumulada.
    El pulso tiene integral Qmax*tau/2 y alcanza Qmax en tau/2.
    """
    if options["source_type"] == "constant":
        return options["source_w_m3"]
    tau = options["source_duration_days"]*86400
    return options["qmax_w_m3"]*0.5*(1-math.cos(2*math.pi*time_s/tau)) if 0 <= time_s < tau else 0.0


def _dashboard_dt(options, limit):
    """El paso automático resuelve el pulso con al menos cien pasos por período."""
    automatic = 0.8*limit
    if options["source_type"] == "cosine":
        automatic = min(automatic, options["source_duration_days"]*86400/100)
    return options["dt_s"] or automatic


@lru_cache(maxsize=3)
def _meshes(path, fingerprint):
    """La huella forma parte de la clave: guardar el IFC invalida la caché."""
    _, guids = case_ifc(CONFIG, path)
    meshes, source = load_ifc_meshes(path, guids)
    if source["sha256"] != fingerprint:
        raise ValueError("El IFC cambió durante la lectura; vuelva a calcular")
    return meshes, source


@lru_cache(maxsize=3)
def _grid(path, fingerprint, resolution):
    meshes, source = _meshes(path, fingerprint)
    # Estima la memoria antes de construir arrays grandes.
    low = np.min([m.vertices.min(axis=0) for m in meshes], axis=0)
    high = np.max([m.vertices.max(axis=0) for m in meshes], axis=0)
    requested = np.array([resolution, resolution, 1.1*resolution])
    if np.prod(np.ceil((high-low)/requested)) > 200_000:
        raise ValueError("Grilla demasiado grande para el visor; aumente el tamaño de celda")
    return voxelize(meshes, requested, source)


def _identity():
    path, _ = case_ifc(CONFIG)
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def metadata():
    """Obtiene geometría y material comunes del IFC actual, sin resolver 1D."""
    import ifcopenshell
    import ifcopenshell.util.element
    import json
    from thermal1d.ifc_input import THERMAL_PROPERTIES, THERMAL_PSET

    path, fingerprint = _identity()
    meshes, source = _meshes(path, fingerprint)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    model = ifcopenshell.open(path)
    psets = ifcopenshell.util.element.get_psets(model.by_guid(config["ifc"]["thermal_property_guid"]))
    material = {field: psets[THERMAL_PSET][name] for field, name in THERMAL_PROPERTIES.items()}
    defaults = {**DEFAULTS, **material}
    low = np.min([m.vertices.min(axis=0) for m in meshes], axis=0)
    high = np.max([m.vertices.max(axis=0) for m in meshes], axis=0)
    defaults.update(dict(zip(("foundation_x_m","foundation_y_m","foundation_height_m"),(high-low).tolist())))
    validate_options(defaults)
    return {"defaults": defaults, "ifc": {**source, "lengths_m": (high-low).tolist(), "components": len(meshes)},
            "environment": environment_inputs(),
            "data_status": "Ensayos sintéticos para exploración térmica.", "max_steps": 8000}


@lru_cache(maxsize=1)
def environment_inputs():
    """Comparte los supuestos de E10 y un ciclo sintético horario con el HTML portátil."""
    config = json.loads((ROOT / "config" / "environment_g8.json").read_text(encoding="utf-8"))
    start = config["construction"]["start_utc"]
    functions = synthetic_series(start, 2).boundary_functions(start)
    weather = {
        name: [functions[name](hour * HOUR) for hour in range(25)]
        for name in ("air_c", "wind_10m_m_s")
    }
    # La media solar de la hora previa se interpola desde centros de hora.
    weather["shortwave_w_m2"] = [functions["shortwave_w_m2"]((hour + 0.5) * HOUR)
                                for hour in range(-1, 24)]
    return {**{key: config[key] for key in ("convection", "solar", "formwork", "insulation", "soil")},
            "weather": weather, "max_step_s": config["demo_section"]["dt_s"],
            "origin": "ciclo horario sintético E10 repetido cada 24 h"}


def environment_boundaries(o, bottom):
    """Usa capas en serie por orientación y, opcionalmente, una base equivalente."""
    inputs = environment_inputs()
    series = inputs["weather"]
    def weather(name, shift=0):
        return lambda t: float(np.interp((t / HOUR + shift) % 24, np.arange(25), series[name]))
    wind = o["environment_wind"] == "synthetic"
    solar = o["environment_solar"] == "synthetic"
    strip = o["environment_formwork"]
    form = inputs["formwork"]
    blanket = inputs["insulation"]
    layer = Layer("moldaje E10", form["thickness_m"], form["conductivity_w_mk"])
    side_layers = {"none": LayerSchedule(), "permanent": LayerSchedule(((0, (layer,)),)),
                   "scheduled": LayerSchedule.formwork_removed_at(o["environment_strip_h"] * HOUR, layer)}[strip]
    top_layers = LayerSchedule(((0, (Layer("manta E10", blanket["thickness_m"],
                                          blanket["conductivity_w_mk"]),)),)) if o["environment_insulation"] == "blanket" else LayerSchedule()
    conv = {key: value for key, value in inputs["convection"].items() if key != "source"}
    common = dict(air_c=weather("air_c"), wind_10m_m_s=weather("wind_10m_m_s") if wind else 0,
                  shortwave_w_m2=weather("shortwave_w_m2", 0.5) if solar else 0,
                  h_w_m2k=None if wind else o["environment_h"], max_wind_m_s=max(series["wind_10m_m_s"]), **conv)
    s = inputs["solar"]
    side = SurfaceExposure(**common, layers=side_layers, solar_absorptance=s["absorptance_formwork"]
                           if strip != "none" else s["absorptance_concrete"], solar_factor=s["side_factor"])
    top = SurfaceExposure(**common, layers=top_layers, solar_absorptance=s["absorptance_concrete"], solar_factor=s["top_factor"])
    exposed = SurfaceMap((Region(side, frozenset({"x-", "x+", "y-", "y+"})),
                          Region(top, frozenset({"z+"}))), default=SurfaceExposure(**common))
    if o["environment_soil"] == "equivalent":
        soil = inputs["soil"]
        bottom = Robin(soil["conductivity_w_mk"] / soil["depth_m"], soil["deep_temperature_c"])
    faces = {key: exposed for key in ("x-", "x+", "y-", "y+", "z+")}
    faces["z-"] = bottom
    return faces, exposed, bottom


def _boundary(kind, temperature, h, flux, resistance=0.0):
    if kind == "dirichlet":
        return Dirichlet(temperature)
    if kind == "neumann":
        return Neumann(flux)
    return Robin(effective_h(h, resistance), temperature)


def _description(boundary):
    if isinstance(boundary, Dirichlet):
        return f"Dirichlet · {boundary.temperature_c:g} °C"
    if isinstance(boundary, Neumann):
        return "Adiabático · flujo 0 W/m²" if boundary.flux_in_w_m2 == 0 else f"Neumann · entran {boundary.flux_in_w_m2:g} W/m²"
    return f"Robin · aire {boundary.ambient_c:g} °C · h efectivo {boundary.h_w_m2k:g} W/(m²·K)"


def run_simulation(data):
    """Resuelve con el código del proyecto y entrega campos, historia y cortes.

    Los controles prevalecen en esta ejecución; no escriben al IFC ni al JSON.
    La geometría procede del IFC, con escalado opcional explícito. Las vertidas
    admiten modo simultáneo o activación temporal con cronograma sintético.
    """
    o = validate_options(data)
    common = _boundary(o["boundary_type"], o["boundary_c"], o["h_w_m2k"], o["flux_in_w_m2"], o["resistance_m2k_w"])
    bottom = _boundary(o["bottom_type"], o["bottom_c"], o["bottom_h_w_m2k"], o["bottom_flux_in_w_m2"])
    duration = o["duration_days"]*86400
    heat_source = (lambda t: source_value(o, t)) if o["source_type"] == "cosine" else o["source_w_m3"]
    source = None
    origin = np.zeros(3)
    k, rho, cp = o["conductivity_w_mk"], o["density_kg_m3"], o["specific_heat_j_kgk"]
    mode = o["mode"]
    use_environment = o["environment_mode"] == "e10"
    if mode == "1d":
        path, fingerprint = _identity()
        meshes, source = _meshes(path, fingerprint)
        length = max(m.vertices[:, 2].max() for m in meshes)-min(m.vertices[:, 2].min() for m in meshes)
        p = Parameters1D(float(length), o["nodes"], k, rho, cp, 1e-9, duration, bottom, common, heat_source)
        limit = p.max_stable_dt_s
        p = replace(p, dt_s=_dashboard_dt(o, limit))
        shape = (p.nodes,)
        active = np.ones(shape, dtype=bool)
        coordinates = np.arange(p.nodes)*p.dx_m
        wave = np.sin(np.pi*coordinates/p.length_m) if o["profile"] == "seno" else np.zeros(shape)
        initial = o["initial_c"]+o["amplitude_c"]*wave
        steps = math.ceil(duration/p.dt_s)
        _check_budget(steps)
        result = solve1d(p, initial, save_every=max(1, math.ceil(steps/24)))
        energy = energy_per_area_j_m2(p, result.temperature_c)
        positions = np.column_stack((coordinates, np.zeros(p.nodes), np.zeros(p.nodes)))
        spacing = np.array([p.dx_m, 0.0, 0.0])
        lengths = np.array([p.length_m, 0.0, 0.0])
        alpha = p.alpha_m2_s
        balance_error = None
    else:
        dim = 2 if mode == "2d" else 3
        if mode == "fundacion":
            path, fingerprint = _identity()
            grid = _grid(path, fingerprint, o["resolution_m"])
            shape, active = grid.component.shape, grid.active
            if o["pour_count"] > shape[2]:
                raise ValueError("Hay vertidas sin celdas: use una malla más fina o reduzca la cantidad de vertidas")
            lengths = grid.lengths_m
            origin = grid.origin_m
            source = grid.report["ifc_input"]
            scale = np.ones(3)
            if o["foundation_geometry"] == "scaled":
                lengths = np.array([o["foundation_x_m"],o["foundation_y_m"],o["foundation_height_m"]])
                scale = lengths/grid.lengths_m
            source = {**source,"geometry_transform":{"type":o["foundation_geometry"],"scale_xyz":scale.tolist(),
                      "reference_lengths_m":grid.lengths_m.tolist()}}
        else:
            shape = (o["nodes"],)*dim
            lengths = np.array([o["length_x_m"], o["length_y_m"], o["length_z_m"]][:dim])
            active = np.ones(shape, dtype=bool)
        faces = {name: common for name in ("x-", "x+", "y-", "y+", "z-", "z+")[:2*dim]}
        faces["y-" if dim == 2 else "z-"] = bottom
        exposed = common if mode == "fundacion" else None
        if use_environment:
            faces, exposed, bottom = environment_boundaries(o, bottom)
        p = Parameters(shape, tuple(lengths), k, rho, cp, 1e-9, duration, faces,
                       active=active, source_w_m3=heat_source, exposed=exposed)
        c = prepare(p)
        limit = min(c.general_dt_s, c.local_dt_s)
        p = replace(p, dt_s=_dashboard_dt(o, limit))
        if use_environment:
            p = replace(p, dt_s=min(p.dt_s, environment_inputs()["max_step_s"]))
        steps = math.ceil(duration/p.dt_s)
        _check_budget(steps)
        wave = sine_initial(p) if o["profile"] == "seno" else np.zeros(shape)
        staged = mode == "fundacion" and o["construction_mode"] == "staged"
        if staged:
            from thermal3d.construction import Pour, CosineHydration, build_plan, solve_construction
            from thermal3d.voxel import VoxelGrid
            from types import SimpleNamespace
            rows = schedule_for(o)
            plan = build_plan(VoxelGrid(origin, lengths, p.spacing_m, grid.component, {}), [
                Pour(i+1, i/o["pour_count"], (i+1)/o["pour_count"], row["start_days"]*86400, row["placement_c"])
                for i, row in enumerate(rows)])
            hydration = (CosineHydration(o["qmax_w_m3"], o["source_duration_days"]*86400)
                         if o["source_type"] == "cosine" else SimpleNamespace(
                             duration_s=duration*100, rate=lambda age: np.where(age >= 0, o["source_w_m3"], 0.0)))
            # Cota conservadora para cualquier interfaz temporal Dirichlet/Robin.
            conservative = 0.8/(4*float(p.alpha_m2_s)*float(np.sum(1/p.spacing_m**2)))
            cap = hydration.duration_s/100
            p = replace(p, dt_s=min(p.dt_s, conservative, cap), source_w_m3=0)
            limit = conservative/0.8
            steps = math.ceil(duration/p.dt_s)+o["pour_count"]
            _check_budget(steps)
            result = solve_construction(p, plan, hydration, save_every=max(1, math.ceil(steps/24)),
                                        activation_energy_j_mol=o["activation_energy_j_mol"])
        else:
            result = solve(p, o["initial_c"]+o["amplitude_c"]*wave, save_every=max(1, math.ceil(steps/24)))
        energy = result.energy_j
        balance_error = float(np.max(np.abs(result.energy_balance_error_j))/max(1.0, float(np.max(np.abs(energy)))))
        local_indices = np.column_stack(np.unravel_index(np.flatnonzero(active), shape))
        positions = np.zeros((len(local_indices), 3))
        positions[:, :dim] = origin[:dim]+(local_indices+0.5)*p.spacing_m
        spacing = np.zeros(3)
        spacing[:dim] = p.spacing_m
        if dim == 2:
            lengths = np.r_[lengths, 0.0]
        alpha = p.alpha_m2_s
    temperatures = result.temperature_c[:, active]
    active_indices = np.flatnonzero(active)
    center_index = tuple(np.asarray(shape)//2)
    if not active[center_index]:
        center_position = origin+lengths/2
        probe = int(np.argmin(np.sum((positions-center_position)**2, axis=1)))
    else:
        probe = int(np.searchsorted(active_indices, np.ravel_multi_index(center_index, shape)))
    staged = mode == "fundacion" and o["construction_mode"] == "staged"
    frame_active = result.active[:, active] if staged else np.ones_like(temperatures, bool)
    temperatures = np.where(frame_active, temperatures, np.nan)
    def values_or_none(values):
        return [float(v) if np.isfinite(v) else None for v in values]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nansum(temperatures, axis=1)/frame_active.sum(axis=1)
    minimum = [float(t[a].min()) if a.any() else None for t, a in zip(temperatures, frame_active)]
    maximum = [float(t[a].max()) if a.any() else None for t, a in zip(temperatures, frame_active)]
    if mode == "1d":
        weights = np.ones(shape)
        weights[[0, -1]] = 0.5
        mean = temperatures@weights/weights.sum()
    boundary_used = {"laterales_y_expuestas": _description(common), "base": _description(bottom)}
    if use_environment:
        boundary_used["laterales_y_expuestas"] = "Robin ambiental E10 · aire sintético y opciones por orientación"
        if o["environment_soil"] == "equivalent":
            boundary_used["base"] = "Suelo equivalente · " + boundary_used["base"]
    pour_plan = None
    if mode == "fundacion":
        ids = np.floor((local_indices[:,2]+0.5)*o["pour_count"]/shape[2]).astype(int)
        counts = np.bincount(ids,minlength=o["pour_count"])
        if np.any(counts == 0):
            raise ValueError("Hay vertidas sin celdas: use una malla más fina o reduzca la cantidad de vertidas")
        pour_plan = {"type":"Capas horizontales de igual altura; sin cronograma de colocación",
                     "simultaneous":True,"cell_pour_id":(ids+1).tolist(),"layers":[
            {"id":i+1,"z_min_m":float(origin[2]+lengths[2]*i/o["pour_count"]),
             "z_max_m":float(origin[2]+lengths[2]*(i+1)/o["pour_count"]),
             "cells":int(counts[i]),"voxel_volume_m3":float(counts[i]*np.prod(p.spacing_m))}
             for i in range(o["pour_count"])]}
    curve_times = set((np.arange(201)*duration/200).tolist()+result.time_s.tolist())
    if o["source_type"] == "cosine":
        tau = o["source_duration_days"]*86400
        curve_times.update(t for t in (tau/2,tau) if t <= duration)
    curve_times = sorted(curve_times)
    if staged:
        pour_plan["simultaneous"] = False
        pour_plan["type"] = "Construcción por etapas · edad local"
        for layer, row in zip(pour_plan["layers"], rows):
            layer.update(start_s=row["start_days"]*86400, placement_c=row["placement_c"])
        curve_times = sorted(set(curve_times) | {row["start_days"]*86400+offset
                             for row in rows for offset in (0, o["source_duration_days"]*43200, o["source_duration_days"]*86400)
                             if row["start_days"]*86400+offset <= duration})
    frames = [[float(v) if np.isfinite(v) else None for v in row] for row in np.round(temperatures, 5)]
    equivalent_curve = None
    if staged and o["activation_energy_j_mol"] > 0:
        from thermal3d.construction import arrhenius_factor
        rates = np.zeros_like(result.temperature_c)
        rates[result.active] = hydration.rate(result.equivalent_age_s[result.active])*arrhenius_factor(
            result.temperature_c[result.active], o["activation_energy_j_mol"])
        equivalent_curve = {"time_s": result.time_s.tolist(), "rate_w_m3": [0.0]*len(result.time_s),
                            "layers": [{"id": i+1, "rate_w_m3": rates[:, plan.vertida_id == i+1].mean(axis=1).tolist()}
                                       for i in range(o["pour_count"])],
                            "description": "Potencia instantánea media por vertida; hormigón futuro aporta cero. Arrhenius por celda."}
    return {"mode": mode, "parameters": o, "ifc": source, "shape": list(shape),
            "dimension": len(shape), "origin_m": origin.tolist(), "lengths_m": lengths.tolist(),
            "spacing_m": spacing.tolist(), "positions_m": np.round(positions, 8).tolist(),
            "active_indices": active_indices.tolist(), "frames_c": frames,
            "time_s": result.time_s.tolist(), "temperature_precision_decimals": 5,
            "history": {"center_c": values_or_none(temperatures[:, probe]), "min_c": minimum,
                        "max_c": maximum, "mean_c": values_or_none(mean), "energy": energy.tolist()},
            "probe_position_m": positions[probe].tolist(), "boundary_used": boundary_used,
            "pour_plan": pour_plan,
            "construction": {"placement_energy_j": result.placement_energy_j.tolist(),
                             "equivalent_age_s": result.equivalent_age_s[:, active].tolist(),
                             "source_heat_in_j": result.source_heat_in_j.tolist(),
                             "boundary_heat_in_j": result.boundary_heat_in_j.tolist()} if staged else None,
            "source_curve": equivalent_curve or {"time_s": curve_times, "rate_w_m3": [source_value(o,t) for t in curve_times],
                             **({"layers": [{"id": i+1, "rate_w_m3": [source_value(o, t-row["start_days"]*86400)
                                 if t >= row["start_days"]*86400 else 0 for t in curve_times]}
                                 for i, row in enumerate(rows)]} if staged else {})},
            "stats": {"cells": int(active.sum()), "steps": result.step_count if staged else steps, "dt_s": p.dt_s, "limit_dt_s": limit,
                      "alpha_m2_s": alpha, "balance_relative_error": balance_error,
                      "energy_unit": "J/m²" if mode == "1d" else "J"},
            "data_status": "Datos sintéticos. Parámetros de esta ejecución desde los controles; archivos del proyecto sin modificar."}


def _check_budget(steps):
    if steps > 8000:
        raise ValueError(f"El caso requiere {steps} pasos. Para el visor, reduzca duración o refine menos la malla (máximo 8000 pasos).")
