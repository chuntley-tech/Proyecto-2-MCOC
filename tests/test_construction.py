"""Ensayos sintéticos de vertidas, edad de hidratación y energía de colocación."""

from dataclasses import replace
import numpy as np
import pytest

from thermal1d.solver import Robin
from thermal3d.solver import Parameters, solve
from thermal3d.voxel import VoxelGrid
from thermal3d.construction import Pour, CosineHydration, build_plan, solve_construction


def setup(pours=None):
    shape = (2, 2, 4)
    grid = VoxelGrid(np.zeros(3), np.ones(3), np.array([.5, .5, .25]), np.ones(shape, np.int16), {})
    if pours is None:
        pours = [Pour(1, 0, .5, 0, 20), Pour(2, .5, 1, .023, 30)]
    plan = build_plan(grid, pours)
    p = Parameters(shape, (1, 1, 1), 1, 2, 3, .01, .051, active=grid.active)
    return grid, plan, p


def test_ids_coverage_and_volume_separate_from_ifc_components():
    grid, plan, _ = setup()
    assert set(np.unique(grid.component)) == {1}
    assert set(np.unique(plan.vertida_id)) == {1, 2}
    assert sum(r["volume_m3"] for r in plan.rows) == 1
    assert np.all(plan.vertida_id[:, :, :2] == 1)


@pytest.mark.parametrize("pours", [
    [Pour(1, 0, .4, 0, 20), Pour(2, .5, 1, 1, 20)],
    [Pour(1, 0, .7, 0, 20), Pour(2, .5, 1, 1, 20)],
    [Pour(1, 0, .5, -1, 20), Pour(2, .5, 1, 1, 20)],
    [Pour(1, 0, .5, 0, 20), Pour(1, .5, 1, 1, 20)],
    [Pour(1, 0, .01, 0, 20), Pour(2, .01, 1, 1, 20)],
])
def test_invalid_plan_rejected(pours):
    with pytest.raises(ValueError):
        setup(pours)


def test_activation_exact_event_no_future_exchange_and_placement_energy():
    _, plan, p = setup()
    r = solve_construction(p, plan, CosineHydration(0, 10), save_every=1)
    event = np.flatnonzero(r.time_s == .023)[0]
    assert not r.active[:event, :, :, 2:].any()
    assert np.all(r.temperature_c[:event, :, :, 2:] == 0)
    # Primera capa adiabática uniforme: la capa futura no la enfría.
    np.testing.assert_array_equal(r.temperature_c[:event, :, :, :2], 20)
    np.testing.assert_array_equal(r.temperature_c[event, :, :, 2:], 30)
    assert r.placement_energy_j[-1] == 2*3*.5*30
    # Sumatorias Float64: error esperado de unas unidades de epsilon.
    assert np.max(np.abs(r.energy_balance_error_j))/r.energy_j[-1] < 1e-14
    assert r.time_s[-1] == p.duration_s


def test_simultaneous_activation_matches_fixed_solver_with_robin():
    _, plan, p = setup([Pour(1, 0, .5, 0, 20), Pour(2, .5, 1, 0, 30)])
    p = replace(p, boundaries={"z+": Robin(2, 10)}, exposed=Robin(2, 10))
    staged = solve_construction(p, plan, CosineHydration(0, 10), save_every=1)
    fixed = solve(p, plan.placement_c, save_every=1)
    # Mismo balance y malla: solo redondeo en el reloj incremental.
    np.testing.assert_allclose(staged.temperature_c, fixed.temperature_c, rtol=0, atol=2e-14)
    assert np.max(np.abs(staged.energy_balance_error_j))/staged.energy_j[0] < 1e-14


def test_age_source_is_left_endpoint_per_pour_and_exact_discrete_integral():
    _, plan, p = setup()
    # k pequeño evita mezcla significativa; se compara contra otro caso sin difusión.
    p = replace(p, conductivity_w_mk=1e-20)
    h = CosineHydration(1300, .2)
    r = solve_construction(p, plan, h, save_every=1)
    expected = plan.placement_c.copy()
    for a, b in zip(r.time_s[:-1], r.time_s[1:]):
        expected += h.rate(a-plan.start_s)*(b-a)/6
    # 2–3 veces el redondeo acumulado en ~27 pasos, no error de discretización.
    np.testing.assert_allclose(r.temperature_c[-1], expected, rtol=0, atol=4e-14)
    assert np.max(np.abs(r.energy_balance_error_j))/r.energy_j[-1] < 1e-14


def test_initial_empty_domain_and_final_activation_saved():
    _, plan, p = setup([Pour(1, 0, 1, .051, 25)])
    r = solve_construction(p, plan, CosineHydration(0, 10), save_every=10000)
    assert len(r.time_s) == 2
    assert r.energy_j[0] == 0 and not r.active[0].any()
    assert r.active[-1].all()
    assert r.placement_energy_j[-1] == 150
    assert r.energy_balance_error_j[-1] == 0


def test_exposed_temporal_surface_and_stability_rebuilt():
    _, plan, p = setup()
    p = replace(p, dt_s=1, exposed=Robin(100, 0))
    r = solve_construction(p, plan, CosineHydration(0, 10), save_every=1)
    # Antes de colocar la segunda capa, la primera pierde calor por su techo.
    assert r.temperature_c[1, 0, 0, 1] < 20
    assert r.boundary_heat_in_j[-1] < 0
    assert np.max(np.abs(r.energy_balance_error_j))/r.energy_j[0] < 1e-14


def test_hydration_total_energy_and_outside_support():
    h = CosineHydration()
    age = np.arange(10001)*h.duration_s/10000
    energy = np.trapezoid(h.rate(age), age)
    assert energy == pytest.approx(h.qmax_w_m3*h.duration_s/2, rel=3e-15)
    np.testing.assert_array_equal(h.rate([-1, h.duration_s, np.inf]), 0)
