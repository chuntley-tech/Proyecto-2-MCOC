"""Regresión contra bucles del ZIP y comportamientos físicos de las guías.

Referencias verificadas: DIFUSION_DE_CALOR_1D_2D_3D.md, §§9–12, 21 y 31.
Los casos 01, 03, 04 y 05 del ZIP son adaptaciones; no copias literales
de los casos de la guía. El caso 06 usa la losa convectiva de la sección 12.
"""

from pathlib import Path

import numpy as np
import pytest

from scripts.run_case import run
from thermal1d.case import load_case
from thermal1d.reference import source_steady_parabola
from thermal1d.solver import solve

EXAMPLES = Path(__file__).resolve().parents[1] / "config" / "ejemplos"


def zip_bar_reference(t_end, left, right_fixed=None, initial=20., source_q0=0.):
    """Bucle de regresión incluido en el ZIP (α = 1e-4, 101 nodos)."""
    alpha, x = 1.0e-4, np.linspace(0.0, 1.0, 101)
    dx = x[1] - x[0]
    dt = 0.45 * dx**2 / alpha
    nsteps = int(np.ceil(t_end / dt))
    dt = t_end / nsteps
    r = alpha * dt / dx**2
    T = np.full(101, initial)
    T[0] = left
    if right_fixed is not None:
        T[-1] = right_fixed
    for _ in range(nsteps):
        Told = T.copy()
        T[1:-1] = Told[1:-1] + r * (Told[2:] - 2.0 * Told[1:-1] + Told[:-2] + source_q0)
        T[0] = left
        T[-1] = right_fixed if right_fixed is not None else Told[-1] + 2 * r * (Told[-2] - Told[-1])
    return dt, T


def zip_robin_reference():
    """Extensión del ZIP: Robin con ambiente sinusoidal, distinto del caso de guía §12."""
    L, k, rho, cp, h = 1.0, 2.0, 2400.0, 900.0, 12.0
    alpha = k / (rho * cp)
    x = np.linspace(0.0, L, 81)
    dx = x[1] - x[0]
    dt = min(0.40 * dx**2 / alpha, 0.40 * (rho * cp * dx) / (2 * h))
    t_end = 48 * 3600.0
    nsteps = int(np.ceil(t_end / dt))
    dt = t_end / nsteps
    r = alpha * dt / dx**2
    T = np.full(81, 20.0)
    for n in range(nsteps):
        Told = T.copy()
        t = n * dt
        Tinf_left = 20.0 + 10.0 * np.sin(2 * np.pi * t / (12.0 * 3600.0))
        T[1:-1] = Told[1:-1] + r * (Told[2:] - 2 * Told[1:-1] + Told[:-2])
        T[0] = Told[0] + dt * (2 * k / (rho * cp * dx**2) * (Told[1] - Told[0])
                               + 2 * h / (rho * cp * dx) * (Tinf_left - Told[0]))
        T[-1] = Told[-1] + dt * (2 * k / (rho * cp * dx**2) * (Told[-2] - Told[-1])
                                 + 2 * h / (rho * cp * dx) * (20.0 - Told[-1]))
    return dt, T


def solve_example(name):
    case = load_case(EXAMPLES / name)
    return case, solve(case.params, case.initial_c, save_every=10**6)


def test_example_01_matches_zip_reference():
    dt, expected = zip_bar_reference(4500., left=0., right_fixed=10.)
    case, result = solve_example("01_dirichlet_video.json")
    assert case.params.dt_s == pytest.approx(dt)
    np.testing.assert_allclose(result.temperature_c[-1], expected, atol=1e-10)


def test_example_03_matches_zip_reference():
    dt, expected = zip_bar_reference(18000., left=60.)
    case, result = solve_example("03_neumann_video.json")
    assert case.params.dt_s == pytest.approx(dt)
    np.testing.assert_allclose(result.temperature_c[-1], expected, atol=1e-10)
    # Caso extendido a 18000 s en el ZIP; la guía §10 usa 6000 s.
    assert result.temperature_c[-1, -1] == pytest.approx(59.400, abs=5e-4)


def test_example_04_matches_zip_reference():
    dt, expected = zip_robin_reference()
    case, result = solve_example("04_robin_video.json")
    assert case.params.dt_s == pytest.approx(dt)
    np.testing.assert_allclose(result.temperature_c[-1], expected, atol=1e-10)


def test_example_05_matches_zip_reference_and_tends_to_parabola():
    dt, expected = zip_bar_reference(4500., left=0., right_fixed=0., initial=0., source_q0=5. / 6000)
    case, result = solve_example("05_fuente_video.json")
    assert case.params.dt_s == pytest.approx(dt)
    np.testing.assert_allclose(result.temperature_c[-1], expected, atol=1e-10)
    steady = source_steady_parabola(case.params, case.x_m)
    assert np.all(result.temperature_c[-1] <= steady + 1e-12)
    assert steady.max() == pytest.approx(1.0417, abs=1e-4)


def test_example_06_slab_cools_and_builds_a_differential():
    case, result = solve_example("06_losa_robin_guia.json")
    temperature = result.temperature_c
    assert np.all((temperature >= 20.) & (temperature <= 70.))
    assert temperature[-1, case.params.nodes // 2] > temperature[-1, 0]


@pytest.mark.parametrize("config", sorted(EXAMPLES.glob("*.json")), ids=lambda path: path.stem)
def test_every_example_runs_and_exports(config, tmp_path):
    summary = run(config, tmp_path)
    assert np.isfinite(summary["max_temperature_c"])
    for name in ("profiles.csv", "history.csv", "profiles.png", "history.png", "summary.json"):
        assert (tmp_path / name).exists()
