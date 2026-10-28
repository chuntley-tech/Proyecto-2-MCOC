"""Verificación sintética independiente de los datos IFC; G05 y difusión §33.

La batería compartida se ejecuta una vez. Las tolerancias se calibraron con
errores medidos: 2–3 veces el error, salvo identidades exactas y redondeo IEEE.
"""

from dataclasses import replace
import numpy as np
import pytest

from thermal1d.solver import Dirichlet, Neumann, Robin
from thermal3d import prepare, solve
from thermal3d.verification import parameters, run_battery


@pytest.fixture(scope="module")
def report():
    return run_battery()


@pytest.mark.parametrize("dim", [2, 3])
def test_sine_and_spatial_order(report, dim):
    group = report[f"convergence_{dim}d"]
    # Errores finos medidos: 1.20147e-4 (2D) y 1.37756e-4 (3D).
    # Los límites son respectivamente 2.08 y 2.54 veces esos errores.
    limit = {2: 0.00025, 3: 0.00035}[dim]
    assert group["rows"][-1]["max_error_c"] < limit
    assert np.all((np.array(group["orders"]) >= 1.8) & (np.array(group["orders"]) <= 2.2))


def test_independent_reference_numbers(report):
    errors = np.array([r["max_error_c"] for r in report["reference_2d"]])
    # Referencias externas redondeadas del enunciado: se exige su margen de 1 %.
    np.testing.assert_allclose(errors, [8.60e-4, 2.18e-4, 5.46e-5], rtol=0.01, atol=0)


@pytest.mark.parametrize("case", ["energy", "mask"])
def test_energy_and_mask(report, case):
    # Medidos 1.775e-16 y 2.191e-16; margen de 2.28–2.82 veces.
    assert report[case]["relative_energy_error"] < 5e-16
    assert report[case]["inactive_max_change_c"] == 0.0


def test_uniform_source_all_cells(report):
    # Error relativo medido 5.351e-14 al restar el incremento a T inicial=2.
    assert report["source_constant"]["max_relative_increment_error"] < 1.2e-13
    assert report["source_constant"]["final_time_s"] == 0.019


def test_variable_source_at_step_start(report):
    # Error relativo medido 3.037e-16; el oráculo suma explícitamente q(t_n) dt.
    assert report["source_variable"]["max_relative_increment_error"] < 8e-16
    assert report["source_variable"]["last_dt_s"] < 0.003


def test_neumann_energy_and_areas(report):
    # Máximo medido 8.065e-15; 2e-14 mantiene margen 2.48, muy inferior a 1e-12.
    assert report["neumann"]["max_relative_energy_error"] < 2e-14


def test_robin_against_fine_nodal_1d(report):
    group = report["robin"]
    assert min(group["orders"]) >= 1.8
    # Medido 4.4702e-5 °C; 1e-4 es 2.24 veces, no una tolerancia en grados.
    assert group["rows"][-1]["max_error_c"] < 1e-4
    # Diferencia de referencias medida 2.601e-7, menos del 1 % del error 3D.
    assert group["rows"][-1]["reference_difference_c"] < 0.01 * group["rows"][-1]["max_error_c"]
    assert group["reference_saved_states"] == [2, 2]
    assert max(row["lateral_spread_c"] for row in group["rows"]) == 0.0


def test_robin_ambient_at_step_start(report):
    # Un solo paso: la fórmula escalar y el balance vectorizado coinciden.
    assert report["robin_time"]["absolute_error_c"] == 0.0


def test_anisotropic_axes_and_1d_equivalent(report):
    group = report["anisotropy"]
    # Medido 6.662e-16 contra modo 1D discreto; 1.5e-15 ≈ 2.25 veces.
    assert group["max_discrete_1d_error_c"] < 1.5e-15
    # Medido 5.552e-17 al cambiar dx,dz: dos veces ese error.
    assert group["changed_xz_max_difference_c"] < 1.2e-16
    # Error de discretización contra seno continuo 3.5431e-4: margen 2.26.
    assert group["max_continuous_1d_error_c"] < 8e-4


def test_no_periodic_wrap(report):
    assert report["nonperiodic"]["heated_first_layer_c"] > 0
    assert report["nonperiodic"]["max_change_distant_c"] == 0.0
    assert report["nonperiodic"]["opposite_face_max_change_c"] == 0.0


def test_both_stability_limits(report):
    for row in report["stability"]["cases"]:
        assert row["below_accepted"] and row["above_rejected"]
        assert f"{row['limit_dt_s']:.12g}" in row["message"]


def test_save_every_and_last_short_step(report):
    group = report["save_every"]
    assert group["saved_states"] == 4
    # Diferencia medida 3.47e-18 s por multiplicación binaria; margen 2.3.
    np.testing.assert_allclose(group["times_s"], group["expected_times_s"], rtol=0, atol=8e-18)


def test_default_saving_does_not_store_every_step():
    p = parameters((3, 4), dt_s=0.0001, duration_s=0.025)
    result = solve(p, np.ones(p.shape))
    assert len(result.time_s) == 4  # inicial, 100, 200, final 250


def test_zero_robin_and_omitted_faces_are_adiabatic():
    p = parameters((3, 4), boundaries={"x-": Robin(0.0, lambda t: 100*t)})
    initial = np.full(p.shape, 2.0)
    np.testing.assert_array_equal(solve(p, initial).temperature_c[-1], initial)


@pytest.mark.parametrize("face", ["x-", "x+", "y-", "y+", "z-", "z+"])
def test_dirichlet_half_cell_and_face_orientation(face):
    p = parameters((3, 4, 5), (0.9, 1.6, 2.5), dt_s=0.001, duration_s=0.001,
                   boundaries={face: Dirichlet(2.0)})
    axis = "xyz".index(face[0])
    result = solve(p, np.zeros(p.shape))
    expected = np.zeros(p.shape)
    indices = [slice(None)] * 3
    indices[axis] = 0 if face[1] == "-" else -1
    expected[tuple(indices)] = 2 * p.alpha_m2_s * p.dt_s * 2.0 / p.spacing_m[axis]**2
    # Oráculo de una sola cara: solo unos ulps al multiplicar conductancia/C.
    np.testing.assert_allclose(result.temperature_c[-1], expected, rtol=4*np.finfo(float).eps, atol=0)


@pytest.mark.parametrize("change", [
    {"shape": (3, 0)}, {"shape": (3.0, 4.0)}, {"lengths_m": (1.0, -1.0, 1.0)},
    {"conductivity_w_mk": 0.0}, {"active": np.ones((2, 2), dtype=bool)},
    {"source_w_m3": float("nan")}, {"boundaries": {"wrong": Neumann()}},
])
def test_invalid_inputs_are_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        p = replace(parameters(), **change)
        solve(p, np.zeros(p.shape))


def test_nonfinite_callback_and_invalid_saving():
    p = parameters((3, 4), source_w_m3=lambda t: float("nan"))
    with pytest.raises(ValueError, match="no finita"):
        solve(p, np.zeros(p.shape))
    with pytest.raises(ValueError, match="save_every"):
        solve(parameters((3, 4)), np.zeros((3, 4)), save_every=0)


def test_battery_runtime(report):
    # Presupuesto exigido de 30 s, no tolerancia numérica. Incluye la referencia 1D fina.
    assert report["battery_elapsed_s"] < 30
    assert report["peak_process_memory_mb"] < 500
