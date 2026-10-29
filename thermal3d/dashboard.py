"""Casos del visor HTML: adapta entradas al solver propio, sin alterar archivos.

Cada respuesta conserva parámetros usados, origen IFC, unidades y tiempos
guardados. Los campos enviados al navegador se redondean a cinco decimales
solo para visualización; estadísticas y balances se calculan con float64.
"""

from dataclasses import replace
from functools import lru_cache
import hashlib
import math
from pathlib import Path

import numpy as np

from scripts.voxelize_foundation import case_ifc
from thermal1d.solver import (Dirichlet, Neumann, Robin, Parameters as Parameters1D,
                              energy_per_area_j_m2, solve as solve1d)
from thermal3d import Parameters, prepare, solve
from thermal3d.reference import sine_initial
from thermal3d.solver import effective_h
from thermal3d.voxel import load_ifc_meshes, voxelize

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
BOUNDS = {"initial_c": (-50, 150), "amplitude_c": (0, 100), "duration_days": (0.001, 30),
          "conductivity_w_mk": (0.05, 10), "density_kg_m3": (100, 5000),
          "specific_heat_j_kgk": (100, 5000), "resolution_m": (0.2, 1.0),
          "length_x_m": (0.1, 20), "length_y_m": (0.1, 20), "length_z_m": (0.1, 20),
          "boundary_c": (-50, 150), "h_w_m2k": (0, 1000), "flux_in_w_m2": (-5000, 5000),
          "resistance_m2k_w": (0, 5), "bottom_c": (-50, 150), "bottom_h_w_m2k": (0, 1000),
          "bottom_flux_in_w_m2": (-5000, 5000), "source_w_m3": (-2000, 5000),
          "qmax_w_m3": (0, 10000), "source_duration_days": (0.001, 30)}


def validate_options(data):
    """Lista cerrada de parámetros y límites para mantener la sesión interactiva."""
    if not isinstance(data, dict) or set(data)-set(DEFAULTS):
        raise ValueError("La solicitud contiene parámetros desconocidos")
    options = {**DEFAULTS, **data}
    if options["mode"] not in ("fundacion", "1d", "2d", "3d"):
        raise ValueError("Caso desconocido")
    if options["profile"] not in ("uniforme", "seno"):
        raise ValueError("Perfil inicial desconocido")
    if options["source_type"] not in ("constant", "cosine"):
        raise ValueError("Fuente desconocida")
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
    return options


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
    validate_options(defaults)
    low = np.min([m.vertices.min(axis=0) for m in meshes], axis=0)
    high = np.max([m.vertices.max(axis=0) for m in meshes], axis=0)
    return {"defaults": defaults, "ifc": {**source, "lengths_m": (high-low).tolist(), "components": len(meshes)},
            "data_status": "Ensayos sintéticos para exploración térmica.", "max_steps": 8000}


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
    La geometría de la fundación siempre procede del archivo guardado.
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
            lengths = grid.lengths_m
            origin = grid.origin_m
            source = grid.report["ifc_input"]
        else:
            shape = (o["nodes"],)*dim
            lengths = np.array([o["length_x_m"], o["length_y_m"], o["length_z_m"]][:dim])
            active = np.ones(shape, dtype=bool)
        faces = {name: common for name in ("x-", "x+", "y-", "y+", "z-", "z+")[:2*dim]}
        faces["y-" if dim == 2 else "z-"] = bottom
        p = Parameters(shape, tuple(lengths), k, rho, cp, 1e-9, duration, faces,
                       active=active, source_w_m3=heat_source, exposed=common if mode == "fundacion" else None)
        c = prepare(p)
        limit = min(c.general_dt_s, c.local_dt_s)
        p = replace(p, dt_s=_dashboard_dt(o, limit))
        steps = math.ceil(duration/p.dt_s)
        _check_budget(steps)
        wave = sine_initial(p) if o["profile"] == "seno" else np.zeros(shape)
        result = solve(p, o["initial_c"]+o["amplitude_c"]*wave, save_every=max(1, math.ceil(steps/24)))
        energy = result.energy_j
        balance_error = float(np.max(np.abs(result.energy_balance_error_j))/max(1.0, abs(energy[0])))
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
    mean = temperatures.mean(axis=1)
    if mode == "1d":
        weights = np.ones(shape)
        weights[[0, -1]] = 0.5
        mean = temperatures@weights/weights.sum()
    boundary_used = {"laterales_y_expuestas": _description(common), "base": _description(bottom)}
    curve_times = set((np.arange(201)*duration/200).tolist()+result.time_s.tolist())
    if o["source_type"] == "cosine":
        tau = o["source_duration_days"]*86400
        curve_times.update(t for t in (tau/2,tau) if t <= duration)
    curve_times = sorted(curve_times)
    return {"mode": mode, "parameters": o, "ifc": source, "shape": list(shape),
            "dimension": len(shape), "origin_m": origin.tolist(), "lengths_m": lengths.tolist(),
            "spacing_m": spacing.tolist(), "positions_m": np.round(positions, 8).tolist(),
            "active_indices": active_indices.tolist(), "frames_c": np.round(temperatures, 5).tolist(),
            "time_s": result.time_s.tolist(), "temperature_precision_decimals": 5,
            "history": {"center_c": temperatures[:, probe].tolist(), "min_c": temperatures.min(axis=1).tolist(),
                        "max_c": temperatures.max(axis=1).tolist(), "mean_c": mean.tolist(), "energy": energy.tolist()},
            "probe_position_m": positions[probe].tolist(), "boundary_used": boundary_used,
            "source_curve": {"time_s": curve_times, "rate_w_m3": [source_value(o,t) for t in curve_times]},
            "stats": {"cells": int(active.sum()), "steps": steps, "dt_s": p.dt_s, "limit_dt_s": limit,
                      "alpha_m2_s": alpha, "balance_relative_error": balance_error,
                      "energy_unit": "J/m²" if mode == "1d" else "J"},
            "data_status": "Datos sintéticos. Parámetros de esta ejecución desde los controles; archivos del proyecto sin modificar."}


def _check_budget(steps):
    if steps > 8000:
        raise ValueError(f"El caso requiere {steps} pasos. Para el visor, reduzca duración o refine menos la malla (máximo 8000 pasos).")
