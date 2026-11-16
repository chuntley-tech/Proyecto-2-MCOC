"""E12: máscara de fuente, integral de la curva exponencial y cubo adiabático."""

import math

import numpy as np
import pytest

from thermal3d.construction import (ConstructionPlan, ExponentialAdiabaticHydration, Pour, build_plan,
                                    solve_construction)
from thermal3d.solver import Parameters
from thermal3d.voxel import VoxelGrid


def test_source_mask_keeps_soil_out_of_hydration():
    shape = (2, 2, 2)
    concrete = np.zeros(shape, dtype=bool)
    concrete[:, :, 0] = True
    soil = ~concrete
    grid = VoxelGrid(np.zeros(3), np.ones(3), np.array([.5, .5, .5]), concrete.astype(np.int16), {})
    sub_plan = build_plan(grid, [Pour(1, 0, 1, 0, 20)])
    plan = ConstructionPlan(np.where(concrete, sub_plan.vertida_id, 0),
                            np.where(concrete, sub_plan.start_s, np.inf),
                            np.where(concrete, sub_plan.placement_c, 0.0), sub_plan.rows)
    p = Parameters(shape, (1, 1, 1), 1e-20, 2, 3, .01, .1, active=np.ones(shape, dtype=bool))
    hydration = ExponentialAdiabaticHydration(theta_inf_c=45, tau_s=3600, density_kg_m3=2, specific_heat_j_kgk=3)
    result = solve_construction(p, plan, hydration, save_every=1, source_mask=concrete,
                                initial_c=np.where(concrete, 20.0, 10.0))
    np.testing.assert_allclose(result.temperature_c[-1][soil], 10.0, atol=1e-12)
    assert np.all(result.equivalent_age_s[:, soil] == 0)
    assert np.all(result.temperature_c[-1][concrete] > 20.0)
    assert result.source_heat_in_j[-1] > 0


def test_exponential_rate_integral_matches_adiabatic_rise():
    hydration = ExponentialAdiabaticHydration(theta_inf_c=45, tau_s=30 * 3600,
                                              density_kg_m3=2400, specific_heat_j_kgk=900)
    age = np.linspace(0.0, 336 * 3600.0, 200001)
    integral = np.trapezoid(hydration.rate(age), age)
    expected = 2400 * 900 * 45 * (1 - math.exp(-336 / 30))
    assert integral == pytest.approx(expected, rel=1e-8)


def test_adiabatic_cube_follows_theta_ad_with_zero_ea():
    shape = (2, 2, 2)
    grid = VoxelGrid(np.zeros(3), np.ones(3), np.array([.5, .5, .5]), np.ones(shape, np.int16), {})
    plan = build_plan(grid, [Pour(1, 0, 1, 0, 20)])
    p = Parameters(shape, (1, 1, 1), 1e-6, 2400, 900, 100.0, 60 * 3600.0,
                   active=np.ones(shape, dtype=bool))
    hydration = ExponentialAdiabaticHydration(theta_inf_c=45, tau_s=30 * 3600,
                                              density_kg_m3=2400, specific_heat_j_kgk=900)
    result = solve_construction(p, plan, hydration, save_every=36, activation_energy_j_mol=0.0)
    expected = 20.0 + hydration.theta_ad_c(result.time_s)
    np.testing.assert_allclose(result.temperature_c[:, 0, 0, 0], expected, rtol=0, atol=0.03)
    assert np.allclose(result.temperature_c, result.temperature_c[:, :1, :1, :1])
