"""Pruebas E10: bordes ambientales, moldaje/desmolde, sol-aire y suelo.

Todos los datos son sintéticos y elegidos para tener solución conocida.
"""

import math

import numpy as np
import pytest

from environment import (FORMWORK_PLYWOOD_18MM, INSULATION_BLANKET_25MM, Layer, LayerSchedule, Region, SoilModel,
                         SurfaceExposure, SurfaceMap, add_soil_layer, convection_h, wind_at_height)
from thermal1d.solver import Dirichlet, Neumann, Robin
from thermal3d.solver import Parameters, advance, prepare


def test_convection_grows_with_wind_and_rejects_negative():
    assert convection_h(0.0) == pytest.approx(5.7)
    assert convection_h(2.0) == pytest.approx(5.7 + 7.6)
    with pytest.raises(ValueError):
        convection_h(-1.0)


def test_wind_profile_reduces_speed_near_ground():
    assert wind_at_height(5.0, 10.0) == pytest.approx(5.0)
    assert wind_at_height(5.0, 2.0) == pytest.approx(5.0 * 0.2 ** 0.14)
    assert wind_at_height(5.0, 2.0) < 5.0


def test_layer_resistance_is_thickness_over_conductivity():
    assert FORMWORK_PLYWOOD_18MM.resistance_m2k_w == pytest.approx(0.018 / 0.13)
    assert INSULATION_BLANKET_25MM.resistance_m2k_w == pytest.approx(0.025 / 0.04)
    with pytest.raises(ValueError):
        Layer("mala", 0.0, 1.0)


def test_formwork_removal_changes_resistance_at_strip_time():
    schedule = LayerSchedule.formwork_removed_at(72 * 3600.0)
    assert schedule.resistance_at(0.0) == pytest.approx(FORMWORK_PLYWOOD_18MM.resistance_m2k_w)
    assert schedule.resistance_at(72 * 3600.0 - 1) == pytest.approx(FORMWORK_PLYWOOD_18MM.resistance_m2k_w)
    assert schedule.resistance_at(72 * 3600.0) == 0.0
    assert schedule.min_resistance_m2k_w == 0.0
    assert 72 * 3600.0 in schedule.change_times_s


def test_sol_air_adds_sun_once_through_the_same_film():
    face = SurfaceExposure(air_c=10.0, wind_10m_m_s=0.0, shortwave_w_m2=600.0, h_w_m2k=15.0,
                           solar_absorptance=0.5, solar_factor=1.0)
    assert face.sol_air_c(0.0) == pytest.approx(10.0 + 0.5 * 600.0 / 15.0)
    # Flujo = h(T_aire − T_s) + a·G cuando no hay capas: convección y sol sumados una sola vez.
    assert face.flux_in_w_m2(0.0, 25.0) == pytest.approx(15.0 * (10.0 - 25.0) + 0.5 * 600.0)
    # Bajo una capa, el sol absorbido afuera atraviesa la misma resistencia que la convección.
    covered = SurfaceExposure(air_c=10.0, shortwave_w_m2=600.0, h_w_m2k=15.0, solar_absorptance=0.5,
                              layers=LayerSchedule(((0.0, (INSULATION_BLANKET_25MM,)),)))
    r = 1 / 15.0 + INSULATION_BLANKET_25MM.resistance_m2k_w
    assert covered.flux_in_w_m2(0.0, 25.0) == pytest.approx((10.0 + 20.0 - 25.0) / r)


def test_without_sun_or_layers_matches_robin():
    """Sin sol ni capas, SurfaceExposure debe dar el mismo resultado que Robin."""
    shape, lengths = (4, 3), (2.0, 1.5)
    base = dict(shape=shape, lengths_m=lengths, conductivity_w_mk=2.0, density_kg_m3=2400.0,
                specific_heat_j_kgk=900.0, dt_s=600.0, duration_s=6000.0)
    a = Parameters(**base, boundaries={"y+": Robin(12.0, 5.0)})
    b = Parameters(**base, boundaries={"y+": SurfaceExposure(air_c=5.0, h_w_m2k=12.0)})
    ta, tb = np.full(shape, 20.0), np.full(shape, 20.0)
    ca, cb = prepare(a), prepare(b)
    for step in range(10):
        advance(a, ca, ta, step * 600.0, 600.0, 0.0)
        advance(b, cb, tb, step * 600.0, 600.0, 0.0)
    np.testing.assert_allclose(ta, tb, rtol=1e-12)


def _column(top, soil=True, depth_m=1.0):
    spacing = 0.1
    nz = 10
    concrete = {"conductivity_w_mk": 2.0, "density_kg_m3": 2400.0, "specific_heat_j_kgk": 900.0}
    if soil:
        grid = add_soil_layer(np.ones((1, nz), bool), (1.0, spacing), (1.0, nz * spacing), concrete,
                              SoilModel(depth_m=depth_m, deep_temperature_c=10.0))
        fields = {k: grid[k] for k in concrete}
        p = Parameters(shape=grid["shape"], lengths_m=grid["lengths_m"], **fields, dt_s=200.0, duration_s=1.0,
                       boundaries={"y+": top, "y-": grid["base"]}, active=grid["active"])
        return p, grid
    p = Parameters(shape=(1, nz), lengths_m=(1.0, nz * spacing), **concrete, dt_s=200.0, duration_s=1.0,
                   boundaries={"y+": top, "y-": Dirichlet(10.0)})
    return p, None


def test_steady_column_matches_series_resistances():
    """Suelo + hormigón + moldaje + película: perfil estacionario = resistencias en serie."""
    top = SurfaceExposure(air_c=0.0, h_w_m2k=10.0, layers=LayerSchedule(((0.0, (FORMWORK_PLYWOOD_18MM,)),)))
    p, grid = _column(top)
    c = prepare(p)
    temperature = np.full(p.shape, 5.0)
    dt = 0.9 * min(c.general_dt_s, c.local_dt_s)
    for step in range(60000):
        before = temperature.copy()
        advance(p, c, temperature, step * dt, dt, 0.0)
        if np.max(np.abs(temperature - before)) < 1e-11:
            break
    r_total = (1.0 / 1.39) + (1.0 / 2.0) + 1 / 10.0 + FORMWORK_PLYWOOD_18MM.resistance_m2k_w
    q = (10.0 - 0.0) / r_total
    z = (np.arange(p.shape[1]) + 0.5) * 0.1
    expected = np.where(z < 1.0, 10.0 - q * z / 1.39, 10.0 - q * (1.0 / 1.39) - q * (z - 1.0) / 2.0)
    np.testing.assert_allclose(temperature[0], expected, atol=1e-6)


def test_energy_balance_with_time_varying_weather_and_strip():
    weather = dict(air_c=lambda t: 8 + 5 * math.sin(2 * math.pi * t / 86400),
                   wind_10m_m_s=lambda t: 3 + 2 * math.cos(2 * math.pi * t / 43200),
                   shortwave_w_m2=lambda t: max(0.0, 700 * math.sin(2 * math.pi * t / 86400)), max_wind_m_s=5.0)
    side = SurfaceExposure(**weather, solar_absorptance=0.6, solar_factor=0.35,
                           layers=LayerSchedule.formwork_removed_at(6 * 3600.0))
    top = SurfaceExposure(**weather, solar_absorptance=0.65,
                          layers=LayerSchedule(((0.0, (INSULATION_BLANKET_25MM,)),)))
    shape = (6, 5)
    p = Parameters(shape=shape, lengths_m=(3.0, 2.5), conductivity_w_mk=2.2, density_kg_m3=2400.0,
                   specific_heat_j_kgk=900.0, dt_s=600.0, duration_s=86400.0,
                   boundaries={"x+": side, "y+": top, "y-": Neumann(0.0)})
    c = prepare(p)
    assert p.dt_s <= min(c.general_dt_s, c.local_dt_s)
    temperature = np.full(shape, 20.0)
    e0 = float(np.sum(c.capacity_j_k * temperature))
    qb = qs = 0.0
    for step in range(144):
        b, s = advance(p, c, temperature, step * 600.0, 600.0, 500.0)
        qb, qs = qb + b, qs + s
    e1 = float(np.sum(c.capacity_j_k * temperature))
    assert abs((e1 - e0) - (qb + qs)) <= 1e-9 * max(abs(qb), abs(qs))


def test_stability_uses_maximum_wind_and_no_layers():
    calm = SurfaceExposure(air_c=0.0, wind_10m_m_s=1.0, max_wind_m_s=1.0)
    windy = SurfaceExposure(air_c=0.0, wind_10m_m_s=1.0, max_wind_m_s=20.0)
    stripped = SurfaceExposure(air_c=0.0, wind_10m_m_s=1.0, max_wind_m_s=1.0,
                               layers=LayerSchedule.formwork_removed_at(3600.0))
    assert windy.min_outer_resistance_m2k_w < calm.min_outer_resistance_m2k_w
    assert stripped.min_outer_resistance_m2k_w == pytest.approx(calm.min_outer_resistance_m2k_w)
    base = dict(shape=(4, 4), lengths_m=(2.0, 2.0), conductivity_w_mk=2.0, density_kg_m3=2400.0,
                specific_heat_j_kgk=900.0, dt_s=1.0, duration_s=1.0)
    limit_calm = prepare(Parameters(**base, boundaries={"y+": calm})).local_dt_s
    limit_windy = prepare(Parameters(**base, boundaries={"y+": windy})).local_dt_s
    assert limit_windy < limit_calm


def test_surface_map_assigns_conditions_by_direction_and_cells():
    active = np.zeros((4, 4), bool)
    active[:, :2] = True       # suelo
    active[:2, 2:] = True      # hormigón
    concrete = np.zeros_like(active)
    concrete[:2, 2:] = True
    side = SurfaceExposure(air_c=0.0, h_w_m2k=5.0, name="costado")
    ground = SurfaceExposure(air_c=0.0, h_w_m2k=20.0, name="suelo")
    exposed = SurfaceMap((Region(side, frozenset({"x+"}), concrete), Region(ground, frozenset({"y+"}), ~concrete)))
    p = Parameters(shape=(4, 4), lengths_m=(1.0, 1.0), conductivity_w_mk=1.0, density_kg_m3=1000.0,
                   specific_heat_j_kgk=1000.0, dt_s=1.0, duration_s=1.0, active=active, exposed=exposed)
    c = prepare(p)
    total = {}
    for indices, boundary, g, area in c.faces:
        name = getattr(boundary, "name", type(boundary).__name__)
        total[name] = total.get(name, 0.0) + float(np.sum(area))
    assert total["costado"] == pytest.approx(2 * 0.25)        # dos celdas del costado x+
    assert total["suelo"] == pytest.approx(2 * 0.25)          # dos celdas de suelo descubierto
    assert set(total) == {"costado", "suelo"}               # no hay otras caras expuestas internas


def test_soil_layer_padding_and_properties():
    concrete = {"conductivity_w_mk": 2.2, "density_kg_m3": 2400.0, "specific_heat_j_kgk": 900.0}
    grid = add_soil_layer(np.ones((4, 3), bool), (0.5, 0.5), (2.0, 1.5), concrete,
                          SoilModel(depth_m=1.0, margin_m=0.5, deep_temperature_c=9.0))
    assert grid["shape"] == (6, 5)
    assert grid["soil"][:, :2].all() and not grid["soil"][:, 2:].any()
    assert grid["concrete"][1:5, 2:].all() and grid["concrete"].sum() == 12
    assert not grid["active"][0, 2:].any()                    # margen lateral: aire sobre el suelo
    assert grid["conductivity_w_mk"][0, 0] == pytest.approx(1.39)
    assert grid["conductivity_w_mk"][2, 3] == pytest.approx(2.2)
    assert isinstance(grid["base"], Dirichlet) and grid["base"].temperature_c == 9.0
    with pytest.raises(ValueError):
        add_soil_layer(np.ones((2, 2), bool), (0.3, 0.3), (0.6, 0.6), concrete, SoilModel(depth_m=1.0))
