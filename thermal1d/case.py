"""Lectura de casos térmicos 1D desde JSON (inputs declarativos).

Un caso define propiedades, malla, tiempo, condición inicial, bordes y
fuente. Para responder un problema nuevo basta con copiar un JSON de
`config/ejemplos/` y cambiar valores, o usar `--set` en `scripts.run_case`.

Formato de los bordes ("bottom" es z = 0 y "top" es z = L):
    {"type": "dirichlet", "temperature_c": 20}
    {"type": "neumann", "flux_in_w_m2": 0}
    {"type": "robin", "h_w_m2k": 12, "ambient_c": 20}
    {"type": "robin", "h_w_m2k": 12,
     "ambient_c": {"mean_c": 20, "amplitude_c": 10, "period_h": 12, "phase_h": 0}}

Formato de la condición inicial:
    {"type": "uniform", "temperature_c": 30}
    {"type": "linear", "bottom_c": 10, "top_c": 30}
    {"type": "sine", "amplitude_c": 20}            # + perfil lineal entre bordes Dirichlet
    {"type": "sine", "base_c": 20, "amplitude_c": 20}
    {"type": "profile", "z_m": [0, 1, 3.3], "temperature_c": [20, 35, 20]}

Con "check_stability": false el solver acepta un paso inestable (Fo sobre el
límite). Sirve solo para mostrar la inestabilidad; esos resultados no son válidos.
"""

import copy
from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np

from .solver import Dirichlet, Neumann, Parameters, Robin

THERMAL_KEYS = ("length_m", "nodes", "conductivity_w_mk", "density_kg_m3",
                "specific_heat_j_kgk", "dt_s", "duration_s")


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    params: Parameters
    x_m: np.ndarray
    initial_c: np.ndarray
    config: dict


def ambient_from_spec(spec):
    """Temperatura ambiente constante o sinusoidal: media + amplitud·sen(2π(t − desfase)/período)."""
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return float(spec)
    if isinstance(spec, dict):
        mean_c = float(spec["mean_c"])
        amplitude_c = float(spec.get("amplitude_c", 0.0))
        period_h = float(spec["period_h"])
        phase_h = float(spec.get("phase_h", 0.0))
        if not all(math.isfinite(v) for v in (mean_c, amplitude_c, period_h, phase_h)) or period_h <= 0:
            raise ValueError("El ambiente requiere valores finitos y period_h positivo")

        def ambient(time_s):
            return mean_c + amplitude_c * math.sin(2 * math.pi * (time_s / 3600 - phase_h) / period_h)
        return ambient
    raise ValueError(f"Temperatura ambiente no reconocida: {spec!r}")


def boundary_from_spec(spec):
    kind = str(spec.get("type", "")).lower()
    if kind == "dirichlet":
        return Dirichlet(float(spec["temperature_c"]))
    if kind == "neumann":
        return Neumann(float(spec.get("flux_in_w_m2", 0.0)))
    if kind == "robin":
        return Robin(float(spec["h_w_m2k"]), ambient_from_spec(spec["ambient_c"]))
    raise ValueError(f"Tipo de borde no reconocido: {spec!r}")


def initial_from_spec(spec, p: Parameters, x_m):
    kind = str(spec.get("type", "")).lower()
    x = np.asarray(x_m, dtype=float)
    if kind == "uniform":
        return np.full(p.nodes, float(spec["temperature_c"]))
    if kind == "linear":
        bottom_c, top_c = float(spec["bottom_c"]), float(spec["top_c"])
        return bottom_c + (top_c - bottom_c) * x / p.length_m
    if kind == "sine":
        if "base_c" in spec:
            base = np.full(p.nodes, float(spec["base_c"]))
        elif isinstance(p.bottom, Dirichlet) and isinstance(p.top, Dirichlet):
            base = (p.bottom.temperature_c
                    + (p.top.temperature_c - p.bottom.temperature_c) * x / p.length_m)
        else:
            raise ValueError("Una condición 'sine' sin base_c requiere bordes Dirichlet")
        return base + float(spec["amplitude_c"]) * np.sin(math.pi * x / p.length_m)
    if kind == "profile":
        z_points = np.asarray(spec["z_m"], dtype=float)
        values = np.asarray(spec["temperature_c"], dtype=float)
        if (z_points.ndim != 1 or z_points.shape != values.shape or z_points.size < 2
                or not np.all(np.isfinite(z_points)) or not np.all(np.isfinite(values))
                or np.any(np.diff(z_points) <= 0)):
            raise ValueError("'profile' requiere z_m crecientes y una temperatura por punto")
        if z_points[0] > 0 or z_points[-1] < p.length_m:
            raise ValueError("'profile' debe cubrir todo el dominio [0, L]")
        return np.interp(x, z_points, values)
    raise ValueError(f"Condición inicial no reconocida: {spec!r}")


def apply_override(config: dict, assignment: str) -> dict:
    """Aplica 'ruta.con.puntos=valor' sobre una copia del caso.

    El valor se interpreta como JSON (números, listas, objetos) y, si no lo
    es, como texto. Ejemplo: 'top.h_w_m2k=20' o 'thermal.duration_s=86400'.
    """
    if "=" not in assignment:
        raise ValueError(f"Use ruta=valor: {assignment!r}")
    path, raw_value = assignment.split("=", 1)
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    keys = path.strip().split(".")
    if not all(keys):
        raise ValueError("La ruta de --set no puede contener claves vacías")
    updated = copy.deepcopy(config)
    node = updated
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    return updated


def case_from_config(config: dict) -> Case:
    thermal = config["thermal"]
    missing = [key for key in THERMAL_KEYS if key not in thermal]
    if missing:
        raise ValueError(f"Faltan parámetros térmicos: {missing}")
    p = Parameters(
        **{key: thermal[key] for key in THERMAL_KEYS},
        bottom=boundary_from_spec(config["bottom"]),
        top=boundary_from_spec(config["top"]),
        source_w_m3=float(config.get("source_w_m3", 0.0)),
        check_stability=config.get("check_stability", True),
    )
    x = np.linspace(0, p.length_m, p.nodes)
    info = config.get("case", {})
    return Case(info.get("name", "caso"), info.get("description", ""), p, x,
                initial_from_spec(config["initial"], p, x), config)


def load_case(path, overrides=()) -> Case:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for assignment in overrides:
        config = apply_override(config, assignment)
    return case_from_config(config)
