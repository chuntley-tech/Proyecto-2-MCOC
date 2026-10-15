import numpy as np
import pytest

from thermal1d.solver import Parameters, sine_reference, solve


def parameters(**overrides):
    values = dict(length_m=1., nodes=21, conductivity_w_mk=1.,
                  density_kg_m3=1., specific_heat_j_kgk=1., dt_s=.001,
                  duration_s=.1, bottom_c=20., top_c=20.)
    return Parameters(**(values | overrides))


def test_uniform_temperature_is_preserved():
    p = parameters()
    result = solve(p, np.full(p.nodes, 20.))
    np.testing.assert_allclose(result.temperature_c, 20., atol=1e-12)


def test_unequal_boundaries_preserve_linear_steady_state():
    p = parameters(bottom_c=10., top_c=30.)
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


def test_spatial_refinement_reduces_error():
    # Un dt pequeño y común permite observar principalmente el error espacial.
    errors = []
    for nodes in (11, 21, 41):
        p = parameters(nodes=nodes, dt_s=1e-5)
        x = np.linspace(0, 1, nodes)
        result = solve(p, sine_reference(p, x, 0, 10.))
        errors.append(np.max(np.abs(result.temperature_c[-1] - sine_reference(p, x, .1, 10.))))
    assert errors[0] / errors[1] > 3
    assert errors[1] / errors[2] > 3


def test_last_step_reaches_requested_time():
    p = parameters(duration_s=.0025)
    result = solve(p, np.full(p.nodes, 20.))
    np.testing.assert_allclose(result.time_s, [0, .001, .002, .0025])


@pytest.mark.parametrize("change", [
    {"dt_s": .01}, {"length_m": 0}, {"nodes": 2}, {"nodes": 4.5},
    {"density_kg_m3": -1}, {"conductivity_w_mk": float("nan")},
    {"duration_s": 0}, {"top_c": float("inf")}, {"specific_heat_j_kgk": 0},
])
def test_invalid_parameters_are_rejected(change):
    with pytest.raises(ValueError):
        parameters(**change)


@pytest.mark.parametrize("initial", [[20.] * 20, [float("nan")] * 21, [30.] * 21])
def test_invalid_initial_state_is_rejected(initial):
    with pytest.raises(ValueError):
        solve(parameters(), initial)
