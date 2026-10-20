import math

import numpy as np
import pytest

from thermal1d.reference import (
    linear_steady_state, sine_reference, sine_reference_semidiscrete, slab_step_reference,
    source_steady_parabola, uniform_source_adiabatic,
)
from thermal1d.solver import Dirichlet, Neumann, Parameters, Robin, energy_per_area_j_m2, solve


def parameters(**overrides):
    values = dict(length_m=1., nodes=21, conductivity_w_mk=1., density_kg_m3=1.,
                  specific_heat_j_kgk=1., dt_s=.001, duration_s=.1,
                  bottom=Dirichlet(20.), top=Dirichlet(20.))
    return Parameters(**(values | overrides))


def concrete(**overrides):
    """Propiedades del caso de verificación G8 (sintéticas)."""
    values = dict(length_m=3.3, nodes=67, conductivity_w_mk=2.2, density_kg_m3=2400.,
                  specific_heat_j_kgk=900., dt_s=600., duration_s=3 * 86400.,
                  bottom=Dirichlet(20.), top=Dirichlet(20.))
    return Parameters(**(values | overrides))


# --- Dirichlet: verificación contra soluciones exactas -------------------------------------

def test_uniform_temperature_is_preserved():
    p = parameters()
    result = solve(p, np.full(p.nodes, 20.))
    np.testing.assert_allclose(result.temperature_c, 20., atol=1e-12)


def test_unequal_boundaries_preserve_linear_steady_state():
    p = parameters(bottom=Dirichlet(10.), top=Dirichlet(30.))
    initial = np.linspace(10., 30., p.nodes)
    result = solve(p, initial)
    np.testing.assert_allclose(result.temperature_c[-1], initial, atol=1e-12)


def test_exact_sine_solution_and_maximum_principle():
    p = parameters(nodes=41, dt_s=.0001)
    x = np.linspace(0, p.length_m, p.nodes)
    result = solve(p, sine_reference(p, x, 0, 10.))
    reference = sine_reference(p, x, p.duration_s, 10.)
    assert np.max(np.abs(result.temperature_c[-1] - reference)) < .002
    assert np.min(result.temperature_c) >= 20. - 1e-12
    assert np.max(result.temperature_c) <= 30. + 1e-12


def test_spatial_refinement_is_second_order():
    # Δt pequeño y común: domina el error espacial, que debe bajar ~4 veces al dividir Δz por 2.
    errors = []
    for nodes in (11, 21, 41):
        p = parameters(nodes=nodes, dt_s=1e-5)
        x = np.linspace(0, 1, nodes)
        result = solve(p, sine_reference(p, x, 0, 10.), save_every=10**6)
        errors.append(np.max(np.abs(result.temperature_c[-1] - sine_reference(p, x, .1, 10.))))
    ratios = np.array(errors[:-1]) / np.array(errors[1:])
    assert np.all((ratios > 3.5) & (ratios < 4.6))


def test_temporal_refinement_is_first_order():
    # Δz fijo; se compara con la solución exacta del sistema semidiscreto para aislar el error en Δt.
    errors = []
    for dt in (2e-4, 1e-4, 5e-5):
        p = parameters(nodes=21, dt_s=dt)
        x = np.linspace(0, 1, p.nodes)
        result = solve(p, sine_reference(p, x, 0, 10.), save_every=10**6)
        exact = sine_reference_semidiscrete(p, x, p.duration_s, 10.)
        errors.append(np.max(np.abs(result.temperature_c[-1] - exact)))
    ratios = np.array(errors[:-1]) / np.array(errors[1:])
    assert np.all((ratios > 1.8) & (ratios < 2.2))


def test_dirichlet_replaces_initial_boundary_values():
    p = parameters(bottom=Dirichlet(10.), top=Dirichlet(10.), duration_s=.003)
    result = solve(p, np.full(p.nodes, 30.))
    assert result.temperature_c[0, 0] == 10. and result.temperature_c[0, -1] == 10.
    np.testing.assert_allclose(result.temperature_c[0, 1:-1], 30.)


def test_slab_step_change_matches_fourier_series():
    # Losa a 30 °C cuyas caras pasan bruscamente a 10 °C (problema clásico).
    p = concrete(bottom=Dirichlet(10.), top=Dirichlet(10.))
    result = solve(p, np.full(p.nodes, 30.))
    exact = slab_step_reference(p, result.x_m, p.duration_s, 30.)
    assert np.max(np.abs(result.temperature_c[-1] - exact)) < .01


def test_last_step_reaches_requested_time():
    p = parameters(duration_s=.0025)
    result = solve(p, np.full(p.nodes, 20.))
    np.testing.assert_allclose(result.time_s, [0, .001, .002, .0025])


def test_save_every_keeps_first_and_last_instants():
    p = parameters(duration_s=.010)
    result = solve(p, np.full(p.nodes, 20.), save_every=3)
    np.testing.assert_allclose(result.time_s, [0, .003, .006, .009, .010])


# --- Neumann ------------------------------------------------------------------------------

def test_adiabatic_domain_conserves_energy():
    p = parameters(bottom=Neumann(0.), top=Neumann(0.), duration_s=.2)
    x = np.linspace(0, 1, p.nodes)
    initial = 20 + 30 * np.exp(-((x - .35) / .12)**2)
    result = solve(p, initial)
    energy = energy_per_area_j_m2(p, result.temperature_c)
    np.testing.assert_allclose(energy, energy[0], rtol=1e-12)
    assert np.ptp(result.temperature_c[-1]) < np.ptp(initial)


def test_imposed_flux_adds_exactly_q_times_t():
    p = parameters(bottom=Neumann(50.), top=Neumann(0.), duration_s=.05)
    result = solve(p, np.full(p.nodes, 20.))
    energy = energy_per_area_j_m2(p, result.temperature_c)
    np.testing.assert_allclose(energy - energy[0], 50. * result.time_s, rtol=1e-10, atol=1e-12)


def test_fixed_bottom_and_adiabatic_top_tend_to_bottom_temperature():
    # Mecanismo de Difusión §10: toda la barra tiende a la temperatura impuesta.
    p = parameters(bottom=Dirichlet(60.), top=Neumann(0.), dt_s=.001, duration_s=10.)
    result = solve(p, np.full(p.nodes, 20.), save_every=10**6)
    np.testing.assert_allclose(result.temperature_c[-1], 60., atol=1e-6)


# --- Robin --------------------------------------------------------------------------------

@pytest.mark.parametrize("bottom, top", [
    (Dirichlet(12.), Robin(15., 5.)),
    (Robin(8., 30.), Robin(15., 5.)),
    (Neumann(40.), Robin(15., 5.)),
])
def test_robin_steady_state_matches_analytic_profile(bottom, top):
    p = parameters(conductivity_w_mk=2.2, bottom=bottom, top=top, dt_s=4e-4, duration_s=12.)
    result = solve(p, np.full(p.nodes, 25.), save_every=10**6)
    np.testing.assert_allclose(result.temperature_c[-1], linear_steady_state(p, result.x_m), atol=1e-8)


def test_hot_slab_loses_heat_to_cold_air():
    p = concrete(length_m=1., nodes=81, conductivity_w_mk=2., dt_s=67.5, duration_s=48 * 3600.,
                 bottom=Robin(12., 20.), top=Robin(12., 20.))
    result = solve(p, np.full(p.nodes, 70.))
    temperature = result.temperature_c
    energy = energy_per_area_j_m2(p, temperature)
    assert np.all(np.diff(energy) < 0)
    assert np.all((temperature >= 20.) & (temperature <= 70.))
    assert np.all(temperature[1:, p.nodes // 2] >= temperature[1:, 0])


def test_robin_ambient_can_change_in_time():
    ambient = lambda t: 20. + 10. * math.sin(2 * math.pi * t / 43200.)
    p = concrete(length_m=1., nodes=81, conductivity_w_mk=2., dt_s=67.5, duration_s=3 * 3600.,
                 bottom=Robin(12., ambient), top=Robin(12., 20.))
    result = solve(p, np.full(p.nodes, 20.))
    # Con el aire más cálido durante las primeras horas, la cara inferior se calienta.
    assert result.temperature_c[-1, 0] > 20.5
    assert abs(result.temperature_c[-1, -1] - 20.) < 1e-9


def test_robin_stability_limit_is_enforced():
    # Fo = 0,4 < 1/2, pero con Bi = 5 el borde exige Fo ≤ 1/12.
    with pytest.raises(ValueError, match="dt_s"):
        parameters(bottom=Robin(100., 20.), dt_s=.001)
    p = parameters(bottom=Robin(100., 20.), dt_s=.0002)
    assert p.fourier <= p.max_fourier


def test_unstable_step_can_be_forced_to_show_the_instability():
    # Fo = 0,52: con check_stability=False el solver corre y viola el principio del máximo.
    p = parameters(bottom=Dirichlet(10.), top=Dirichlet(10.), dt_s=.0013, check_stability=False)
    assert p.fourier > p.max_fourier
    result = solve(p, np.full(p.nodes, 30.))
    assert result.temperature_c.max() > 30. or result.temperature_c.min() < 10.


# --- Fuente volumétrica -------------------------------------------------------------------

def test_uniform_source_in_adiabatic_domain_rises_linearly():
    p = parameters(bottom=Neumann(0.), top=Neumann(0.), source_w_m3=1000., duration_s=.05)
    result = solve(p, np.full(p.nodes, 20.))
    expected = uniform_source_adiabatic(p, 20., result.time_s)
    np.testing.assert_allclose(result.temperature_c, expected[:, None] * np.ones(p.nodes), rtol=1e-12)


def test_source_with_cold_faces_tends_to_parabola():
    p = parameters(bottom=Dirichlet(0.), top=Dirichlet(0.), source_w_m3=8., duration_s=3.)
    result = solve(p, np.zeros(p.nodes), save_every=10**6)
    np.testing.assert_allclose(result.temperature_c[-1], source_steady_parabola(p, result.x_m), atol=1e-9)


# --- Entradas inválidas -------------------------------------------------------------------

@pytest.mark.parametrize("change", [
    {"dt_s": .01}, {"length_m": 0}, {"nodes": 2}, {"nodes": 4.5},
    {"density_kg_m3": -1}, {"conductivity_w_mk": float("nan")},
    {"duration_s": 0}, {"top": Dirichlet(float("inf"))}, {"specific_heat_j_kgk": 0},
    {"bottom": Robin(-1., 20.)}, {"source_w_m3": float("nan")},
])
def test_invalid_parameters_are_rejected(change):
    with pytest.raises(ValueError):
        parameters(**change)


def test_unknown_boundary_type_is_rejected():
    with pytest.raises(TypeError):
        parameters(top="adiabatico")


@pytest.mark.parametrize("initial", [[20.] * 20, [float("nan")] * 21])
def test_invalid_initial_state_is_rejected(initial):
    with pytest.raises(ValueError):
        solve(parameters(), initial)


def test_energy_uses_half_cells_at_the_boundaries():
    p = parameters(density_kg_m3=2., specific_heat_j_kgk=3.)
    assert energy_per_area_j_m2(p, np.ones(p.nodes)) == pytest.approx(6. * p.length_m)
