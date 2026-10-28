"""Experimentos reproducibles con parámetros exclusivamente sintéticos.

G05 y difusión §§16,19,33: verificar antes de utilizar clima o hidratación.
Estas funciones devuelven métricas, compartidas por pytest y verify_3d.
"""

from dataclasses import replace
import math
import sys
from time import perf_counter

import numpy as np

from thermal1d.solver import Dirichlet, Neumann, Robin, Parameters as Parameters1D, solve as solve1d
from .solver import Parameters, prepare, solve


def peak_memory_mb():
    """Pico de memoria residente del proceso, medido por el sistema operativo."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                        ("peak", ctypes.c_size_t), ("working", ctypes.c_size_t),
                        ("quota_peak_paged", ctypes.c_size_t), ("quota_paged", ctypes.c_size_t),
                        ("quota_peak_nonpaged", ctypes.c_size_t), ("quota_nonpaged", ctypes.c_size_t),
                        ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.peak / 1_000_000
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1_000_000 if sys.platform == "darwin" else 1000)


def parameters(shape=(7, 8, 9), lengths=None, **kwargs):
    """Material sintético k=ρ=cp=1 en SI; no representa hormigón G8."""
    lengths = (1.0,) * len(shape) if lengths is None else lengths
    return Parameters(shape, lengths, 1.0, 1.0, 1.0,
                      kwargs.pop("dt_s", 0.0002), kwargs.pop("duration_s", 0.01), **kwargs)


def sine_case(dim, n, fo=0.01):
    """Seno exacto en centros; Fo por eje fijo salvo ajuste al tiempo final."""
    dx, duration = 1.0 / n, 0.02
    steps = math.ceil(duration / (fo * dx**2))
    faces = {name: Dirichlet(0.0) for name in ("x-", "x+", "y-", "y+", "z-", "z+")[:2*dim]}
    p = parameters((n,) * dim, dt_s=duration / steps, duration_s=duration, boundaries=faces)
    x = (np.arange(n) + 0.5) * dx
    wave = np.sin(np.pi * x)
    initial = wave[:, None] * wave[None, :]
    if dim == 3:
        initial = initial[:, :, None] * wave[None, None, :]
    result = solve(p, initial, save_every=10**9)
    exact = initial * np.exp(-dim * np.pi**2 * p.alpha_m2_s * duration)
    return {"dimension": dim, "n": n, "dx_m": dx, "dt_s": p.dt_s, "steps": steps,
            "fourier_per_axis": p.alpha_m2_s * p.dt_s / dx**2,
            "max_error_c": float(np.max(np.abs(result.temperature_c[-1] - exact)))}


def convergence(dim):
    """Tres mallas y órdenes a partir de errores máximos, no cifras supuestas."""
    rows = [sine_case(dim, n) for n in (10, 20, 40)]
    orders = np.log2(np.array([r["max_error_c"] for r in rows[:-1]]) /
                     np.array([r["max_error_c"] for r in rows[1:]]))
    return {"rows": rows, "orders": orders.tolist()}


def conservation(masked=False):
    """Caja o máscara con hueco y recorte en L, aisladas y sin fuente."""
    p = parameters()
    active = np.ones(p.shape, dtype=bool)
    if masked:
        active[2:4, 2:5, 3:6] = False
        active[:3, :3, :] = False
        p = replace(p, active=active)
    initial = np.random.default_rng(2026).uniform(10, 30, p.shape)
    initial[~active] = -50.0
    result = solve(p, initial, save_every=7)
    return {"relative_energy_error": float(np.max(np.abs(result.energy_j - result.energy_j[0])) / abs(result.energy_j[0])),
            "inactive_max_change_c": float(np.max(np.abs(result.temperature_c[:, ~active] - initial[~active]))) if masked else 0.0,
            "active_cells": int(active.sum())}


def sources(variable=False):
    """Solución uniforme exacta de Euler; incluye un último paso acortado."""
    a, q, initial = 7.0, 3.0, 0.0 if variable else 2.0
    p = parameters((4, 5, 6), dt_s=0.003, duration_s=0.019,
                   source_w_m3=(lambda t: a*t) if variable else q)
    p = replace(p, density_kg_m3=2.0, specific_heat_j_kgk=3.0)
    steps = math.ceil(p.duration_s / p.dt_s)
    starts = np.arange(steps) * p.dt_s
    widths = np.minimum(starts + p.dt_s, p.duration_s) - starts
    energy_density = float(np.sum(a * starts * widths)) if variable else q * p.duration_s
    increment = energy_density / (p.density_kg_m3 * p.specific_heat_j_kgk)
    result = solve(p, np.full(p.shape, initial), save_every=10**9)
    error = float(np.max(np.abs(result.temperature_c[-1] - initial - increment)))
    return {"max_relative_increment_error": error / abs(increment), "expected_increment_c": increment,
            "max_absolute_error_c": error, "steps": steps, "last_dt_s": float(widths[-1]),
            "final_time_s": float(result.time_s[-1])}


def neumann():
    """Flujo entrante en una cara de cada eje: verifica signo y áreas."""
    records = []
    for axis, face in enumerate(("x-", "y+", "z-")):
        p = parameters((4, 5, 6), (0.8, 1.5, 2.4), dt_s=0.003, duration_s=0.019,
                       boundaries={face: Neumann(5.0)})
        initial = np.full(p.shape, 2.0)
        result = solve(p, initial, save_every=10**9)
        area = float(np.prod(p.lengths_m) / p.lengths_m[axis])
        expected = 5.0 * area * p.duration_s
        error = abs(float(result.energy_j[-1] - result.energy_j[0]) - expected) / expected
        records.append({"face": face, "area_m2": area, "expected_energy_j": expected,
                        "relative_energy_error": error})
    return {"faces": records, "max_relative_energy_error": max(r["relative_energy_error"] for r in records)}


def robin_reference():
    """Robin 3D contra 1D nodal fino, interpolado en centros (sin historial).

    La referencia conserva solo inicial/final. Se calcula otra resolución
    nodal para estimar por refinamiento su incertidumbre de segundo orden.
    """
    begin = perf_counter()
    bottom, top = Robin(1.0, 0.0), Robin(2.0, 0.0)
    refs = []
    for nodes in (1025, 2049):
        # La malla nodal pertenece exclusivamente al solver 1D existente.
        p1 = Parameters1D(1.0, nodes, 1.0, 2.0, 3.0, 1e-10, 0.1, bottom, top)
        p1 = replace(p1, dt_s=0.8 * p1.max_stable_dt_s)
        refs.append(solve1d(p1, np.ones(nodes), save_every=10**9))
    rows = []
    for nz in (16, 32, 64):
        dz = 1.0 / nz
        dt = 0.05 * dz**2 / (1/6)
        p = Parameters((2, 3, nz), (0.7, 0.9, 1.0), 1.0, 2.0, 3.0, dt, 0.1,
                       {"z-": bottom, "z+": top})
        result = solve(p, np.ones(p.shape), save_every=10**9)
        centers = (np.arange(nz) + 0.5) * dz
        exact = np.interp(centers, refs[1].x_m, refs[1].temperature_c[-1])
        coarser = np.interp(centers, refs[0].x_m, refs[0].temperature_c[-1])
        rows.append({"nz": nz, "dz_m": dz, "dt_s": dt,
                     "max_error_c": float(np.max(np.abs(result.temperature_c[-1] - exact))),
                     "reference_difference_c": float(np.max(np.abs(coarser - exact))),
                     "lateral_spread_c": float(np.max(np.ptp(result.temperature_c[-1], axis=(0, 1))))})
    errors = np.array([r["max_error_c"] for r in rows])
    return {"rows": rows, "orders": np.log2(errors[:-1] / errors[1:]).tolist(),
            "reference_nodes": [1025, 2049], "reference_saved_states": [len(r.time_s) for r in refs],
            "elapsed_s": perf_counter() - begin}


def robin_time():
    """Una celda activa aislada: oráculo escalar de un paso con ambiente variable."""
    mask = np.zeros((2, 2, 2), dtype=bool)
    mask[0, 0, 0] = True
    p = parameters((2, 2, 2), (0.8, 1.0, 1.2), dt_s=0.001, duration_s=0.001,
                   boundaries={"x-": Robin(3.0, lambda t: 4.0 + 1000*t)}, active=mask)
    dx, dy, dz = p.spacing_m
    area = dy * dz
    g = area / (1/3 + dx/2)
    expected = 2.0 + p.dt_s * g * (4.0-2.0) / (dx*dy*dz)
    result = solve(p, np.full(p.shape, 2.0))
    return {"expected_temperature_c": float(expected), "absolute_error_c": abs(float(result.temperature_c[-1, 0, 0, 0]) - expected)}


def anisotropy():
    """Variación solo en y: oráculo 1D discreto independiente y referencia continua.

    El seno es autovector del operador centrado con caras Dirichlet. Su factor
    Euler es conocido; cambiar Δx y Δz no puede alterar esa evolución 1D.
    """
    ny, ly, dt, steps = 13, 1.3, 0.0005, 40
    y = (np.arange(ny) + 0.5) * (ly / ny)
    wave = np.sin(np.pi * y / ly)
    factor = 1 - 4 * dt / (ly / ny)**2 * np.sin(np.pi / (2*ny))**2
    exact_discrete = wave * factor**steps
    exact_continuous = wave * np.exp(-(np.pi/ly)**2 * dt*steps)
    outputs = []
    for lengths in ((0.7, ly, 1.8), (2.0, ly, 0.9)):
        p = parameters((2, ny, 3), lengths, dt_s=dt, duration_s=dt*steps,
                       boundaries={"y-": Dirichlet(0.0), "y+": Dirichlet(0.0)})
        initial = np.broadcast_to(wave[None, :, None], p.shape).copy()
        outputs.append(solve(p, initial, save_every=10**9).temperature_c[-1])
    return {"max_discrete_1d_error_c": float(np.max(np.abs(outputs[0] - exact_discrete[None, :, None]))),
            "max_continuous_1d_error_c": float(np.max(np.abs(outputs[0] - exact_continuous[None, :, None]))),
            "changed_xz_max_difference_c": float(np.max(np.abs(outputs[0] - outputs[1]))),
            "spacings_m": [[0.35, 0.1, 0.6], [1.0, 0.1, 0.3]]}


def nonperiodic():
    """Un paso desde una cara caliente no alcanza vecinos lejanos ni el opuesto."""
    p = parameters((7, 4, 3), dt_s=0.001, duration_s=0.001, boundaries={"x-": Dirichlet(1.0)})
    result = solve(p, np.zeros(p.shape), save_every=1)
    return {"heated_first_layer_c": float(np.min(result.temperature_c[-1, 0])),
            "max_change_distant_c": float(np.max(np.abs(result.temperature_c[-1, 2:]))),
            "opposite_face_max_change_c": float(np.max(np.abs(result.temperature_c[-1, -1])))}


def stability():
    """Ensaya ±10⁻⁸ relativo a cada límite; Robin fuerte limita localmente."""
    records = []
    for name, boundaries in (("general", {}), ("local", {"x-": Robin(1e6, 0.0), "y-": Robin(1e6, 0.0), "z-": Robin(1e6, 0.0)})):
        p = parameters((4, 4, 4), boundaries=boundaries)
        c = prepare(p)
        limit = c.general_dt_s if name == "general" else c.local_dt_s
        accepted = prepare(replace(p, dt_s=limit*(1-1e-8)))
        message = ""
        try:
            prepare(replace(p, dt_s=limit*(1+1e-8)))
        except ValueError as error:
            message = str(error)
        records.append({"criterion": name, "limit_dt_s": limit, "below_accepted": accepted is not None,
                        "above_rejected": bool(message), "message": message})
    return {"cases": records}


def saving():
    """Siete pasos, último acortado; inicial, pasos 3/6 y final 7."""
    p = parameters((3, 4), dt_s=0.003, duration_s=0.019)
    result = solve(p, np.ones(p.shape), save_every=3)
    return {"saved_states": len(result.time_s), "times_s": result.time_s.tolist(),
            "expected_times_s": [0.0, 0.009, 0.018, 0.019]}


def run_battery():
    """Ejecuta experimentos pequeños; no llama Blender ni carga el IFC."""
    start = perf_counter()
    report = {"data_status": "Todos los datos son sintéticos de verificación; no mediciones ni predicción G8.",
              "units": "SI: m, s, W, J; temperatura en °C relativa a 0 °C para energía",
              "reference_2d": [sine_case(2, n, fo=0.05) for n in (10, 20, 40)],
              "convergence_2d": convergence(2), "convergence_3d": convergence(3),
              "energy": conservation(), "source_constant": sources(), "source_variable": sources(True),
              "neumann": neumann(), "robin": robin_reference(), "robin_time": robin_time(),
              "mask": conservation(True), "anisotropy": anisotropy(), "nonperiodic": nonperiodic(),
              "stability": stability(), "save_every": saving()}
    report["battery_elapsed_s"] = perf_counter() - start
    report["peak_process_memory_mb"] = peak_memory_mb()
    return report


def acceptance(report):
    """Criterios reproducibles para el script, también ejercitados por pytest.

    Umbrales ajustados a las corridas de calibración y detallados en los tests;
    no son datos físicos del caso G8. Los balances exigen bastante menos de 1e-12.
    """
    d2, d3 = report["convergence_2d"], report["convergence_3d"]
    ref = np.array([r["max_error_c"] for r in report["reference_2d"]])
    r = report["robin"]
    checks = {
        "reference_2d": bool(np.all(np.abs(ref / [8.60e-4, 2.18e-4, 5.46e-5] - 1) < 0.01)),
        "sine_2d": d2["rows"][-1]["max_error_c"] < 0.00025,
        "sine_3d": d3["rows"][-1]["max_error_c"] < 0.00035,
        "orders_2d_3d": bool(np.all((np.array(d2["orders"] + d3["orders"]) >= 1.8) &
                                        (np.array(d2["orders"] + d3["orders"]) <= 2.2))),
        "energy": report["energy"]["relative_energy_error"] < 5e-16,
        "source_constant": report["source_constant"]["max_relative_increment_error"] < 1.2e-13,
        "source_variable": report["source_variable"]["max_relative_increment_error"] < 8e-16,
        "neumann": report["neumann"]["max_relative_energy_error"] < 2e-14,
        "robin": min(r["orders"]) >= 1.8 and r["rows"][-1]["max_error_c"] < 1e-4
                 and r["rows"][-1]["reference_difference_c"] < 0.01 * r["rows"][-1]["max_error_c"]
                 and r["reference_saved_states"] == [2, 2],
        "robin_time": report["robin_time"]["absolute_error_c"] == 0,
        "mask": report["mask"]["relative_energy_error"] < 5e-16 and report["mask"]["inactive_max_change_c"] == 0,
        "anisotropy": report["anisotropy"]["max_discrete_1d_error_c"] < 1.5e-15
                      and report["anisotropy"]["changed_xz_max_difference_c"] < 1.2e-16,
        "nonperiodic": report["nonperiodic"]["max_change_distant_c"] == 0
                       and report["nonperiodic"]["opposite_face_max_change_c"] == 0
                       and report["nonperiodic"]["heated_first_layer_c"] > 0,
        "stability": all(r["below_accepted"] and r["above_rejected"] for r in report["stability"]["cases"]),
        "save_every": report["save_every"]["saved_states"] == 4 and bool(np.allclose(
            report["save_every"]["times_s"], report["save_every"]["expected_times_s"], rtol=0, atol=8e-18)),
        "resources": report["battery_elapsed_s"] < 30 and report["peak_process_memory_mb"] < 500,
    }
    return {name: bool(value) for name, value in checks.items()}
