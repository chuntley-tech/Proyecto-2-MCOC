"""Mejoras del ZIP adaptadas: dos materiales y balance con superficies expuestas.

Todos los parámetros de estas pruebas son sintéticos. No son propiedades
calibradas de hormigón, moldaje o suelo del caso G8.
"""

import numpy as np

from thermal1d.solver import Dirichlet, Neumann, Robin
from .reference import two_layer_steady
from .solver import Parameters, effective_h, prepare, solve


def materials():
    """Perfil estacionario exacto y conductancia de dos medias celdas diferentes."""
    shape = (2, 20)
    y = (np.arange(shape[1])+0.5)/shape[1]
    k = np.broadcast_to(np.where(y < 0.5, 1.0, 4.0), shape).copy()
    exact = np.broadcast_to(two_layer_steady(y, 0.5, 1.0, 1.0, 4.0, 10.0, 40.0), shape).copy()
    p = Parameters(shape, (1.0, 1.0), k, 2.0, 3.0, 0.0001, 0.01,
                   {"y-": Dirichlet(10.0), "y+": Dirichlet(40.0)})
    c = prepare(p)
    result = solve(p, exact, save_every=10**9)
    expected_g = (2*1.0*4.0/(1.0+4.0)) * 0.5/0.05
    return {"max_steady_error_c": float(np.max(np.abs(result.temperature_c[-1]-exact))),
            "interface_conductance_w_k": float(c.gy[0, 9]), "expected_conductance_w_k": expected_g,
            "max_energy_balance_relative_error": float(np.max(np.abs(result.energy_balance_error_j))/result.energy_j[0]),
            "centers_m": y.tolist(), "exact_profile_c": exact[0].tolist(),
            "calculated_profile_c": result.temperature_c[-1, 0].tolist()}


def exposed(h_w_m2k=10.0, ambient_c=0.0, source_w_m3=2.0):
    """Isla activa que pierde calor por sus superficies interiores a la caja."""
    shape = (5, 6, 7)
    active = np.zeros(shape, dtype=bool)
    active[1:4, 1:5, :5] = True
    p = Parameters(shape, (0.6, 0.9, 0.84), 1.0, 1.0, 1.0, 1e-5, 0.0022,
                   {"z-": Neumann()}, active=active, source_w_m3=source_w_m3,
                   exposed=Robin(h_w_m2k, ambient_c))
    initial = np.where(active, 20.0, -50.0)
    result = solve(p, initial, save_every=20)
    return {"max_energy_balance_relative_error": float(np.max(np.abs(result.energy_balance_error_j))/result.energy_j[0]),
            "boundary_heat_in_j": float(result.boundary_heat_in_j[-1]),
            "source_heat_in_j": float(result.source_heat_in_j[-1]),
            "energy_change_j": float(result.energy_j[-1]-result.energy_j[0]),
            "inactive_max_change_c": float(np.max(np.abs(result.temperature_c[:, ~active]-initial[~active]))),
            "time_s": result.time_s.tolist(), "energy_j": result.energy_j.tolist(),
            "boundary_history_j": result.boundary_heat_in_j.tolist(), "source_history_j": result.source_heat_in_j.tolist(),
            "h_w_m2k": h_w_m2k, "ambient_c": ambient_c, "source_w_m3": source_w_m3}


def heterogeneous_energy():
    """Propiedades y capacidades variables con máscara, sin intercambio exterior."""
    rng = np.random.default_rng(2026)
    shape = (4, 5, 6)
    active = np.ones(shape, dtype=bool)
    active[1:3, 2, 2:4] = False
    k = rng.uniform(1, 3, shape)
    rho = rng.uniform(2, 4, shape)
    cp = rng.uniform(3, 5, shape)
    p = Parameters(shape, (0.8, 1.5, 2.4), k, rho, cp, 0.0001, 0.01, active=active)
    result = solve(p, rng.uniform(10, 30, shape), save_every=3)
    return {"relative_energy_error": float(np.max(np.abs(result.energy_j-result.energy_j[0]))/result.energy_j[0])}


def material_source():
    """Primer paso uniforme en temperatura: cada incremento usa su propio ρcp."""
    shape = (3, 4, 5)
    rho = np.arange(1, 61, dtype=float).reshape(shape)
    cp = np.full(shape, 2.0)
    p = Parameters(shape, (0.6, 1.2, 2.0), 1.0, rho, cp, 1e-5, 1e-5, source_w_m3=3.0)
    result = solve(p, np.zeros(shape))
    expected = p.dt_s*3.0/(rho*cp)
    return {"max_relative_cell_error": float(np.max(np.abs(result.temperature_c[-1]/expected-1))),
            "energy_balance_error_j": float(np.max(np.abs(result.energy_balance_error_j)))}


def insulation():
    """Resistencias de ensayo en serie: identidad y caso adiabático h=0."""
    expected = 1/(1/10 + 0.05 + 0.5)
    return {"effective_h_w_m2k": effective_h(10, 0.05, 0.5), "expected_h_w_m2k": expected,
            "zero_h_w_m2k": effective_h(0, 0.05, 0.5)}
