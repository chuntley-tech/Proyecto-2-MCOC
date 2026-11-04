"""Edad equivalente: parámetros sintéticos, sin calibración de mezcla G8."""

import math

import numpy as np
import pytest

from thermal3d.construction import CosineHydration, Pour, build_plan, solve_construction, arrhenius_factor
from thermal3d.solver import Parameters
from thermal3d.voxel import VoxelGrid


def case(temperature=20, delayed=False):
    grid = VoxelGrid(np.zeros(3), np.ones(3), np.array([.5, .5, .25]), np.ones((2, 2, 4), np.int16), {})
    pours = [Pour(1, 0, .5, 0, temperature), Pour(2, .5, 1, .023 if delayed else 0, temperature)]
    return Parameters((2, 2, 4), (1, 1, 1), 1, 2, 3, .003, .051, active=grid.active), build_plan(grid, pours)


@pytest.mark.parametrize("temperature", [5, 20, 40])
def test_isothermal_equivalent_clock(temperature):
    p, plan = case(temperature)
    ea = 35000.0  # Valor exclusivamente sintético para verificar la ecuación.
    r = solve_construction(p, plan, CosineHydration(0, 10), save_every=1, activation_energy_j_mol=ea)
    factor = math.exp(-ea/8.31446261815324*(1/(temperature+273.15)-1/293.15))
    # Isotermo: integración de una constante; solo redondeo Float64.
    np.testing.assert_allclose(r.equivalent_age_s[-1], p.duration_s*factor, rtol=4e-15)
    assert (factor < 1 if temperature < 20 else factor > 1 if temperature > 20 else factor == 1)


def test_clock_starts_at_placement_and_future_cells_stay_zero():
    p, plan = case(20, delayed=True)
    r = solve_construction(p, plan, CosineHydration(0, 10), save_every=1, activation_energy_j_mol=35000)
    event = np.flatnonzero(r.time_s == .023)[0]
    np.testing.assert_array_equal(r.equivalent_age_s[:event+1, :, :, 2:], 0)
    np.testing.assert_allclose(r.equivalent_age_s[-1, :, :, 2:], .051-.023, rtol=4e-15)


def test_chain_rule_and_left_endpoint_against_uniform_scalar_balance():
    p, plan = case(30)
    h, ea = CosineHydration(1300, .2), 35000.0
    r = solve_construction(p, plan, h, save_every=1, activation_energy_j_mol=ea)
    temperature, te = 30.0, 0.0
    for start, end in zip(r.time_s[:-1], r.time_s[1:]):
        factor = math.exp(-ea/8.31446261815324*(1/(temperature+273.15)-1/293.15))
        q = 650*(1-math.cos(2*math.pi*te/.2)) if te < .2 else 0
        temperature += (end-start)*q*factor/6
        te += (end-start)*factor
    # Uniforme/adiabático: no error espacial; diferencias de exp/cos y sumas.
    np.testing.assert_allclose(r.temperature_c[-1], temperature, rtol=0, atol=3e-14)
    np.testing.assert_allclose(r.equivalent_age_s[-1], te, rtol=4e-15)
    assert np.max(np.abs(r.energy_balance_error_j))/r.energy_j[-1] < 1e-14


def test_zero_activation_energy_recovers_chronological_age():
    p, plan = case(40, delayed=True)
    r = solve_construction(p, plan, CosineHydration(1300, .2), save_every=1)
    expected = np.maximum(r.time_s[:, None, None, None]-plan.start_s, 0)
    np.testing.assert_allclose(r.equivalent_age_s, expected, rtol=0, atol=3e-17)


@pytest.mark.parametrize("ea", [-1, float("nan"), float("inf")])
def test_invalid_activation_energy_rejected(ea):
    p, plan = case()
    with pytest.raises(ValueError, match="Ea"):
        solve_construction(p, plan, CosineHydration(), activation_energy_j_mol=ea)


def test_absolute_zero_rejected():
    with pytest.raises(ValueError, match="273.15"):
        arrhenius_factor([-273.15], 35000)
