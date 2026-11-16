"""Verificación de la reconstrucción y la regla probabilística final."""

from types import SimpleNamespace

import numpy as np
import pytest

from scripts.final_campaign import (SOURCE, compare, progressive_plan, schedule, temperature_rising,
                                    trim_missing_forecast_edges, weather_sensitivity)
from thermal3d.critical_temperatures import CriticalTemperatures, temperature_at_depth
from thermal3d.hydration import load_curves
from thermal3d.solver import Parameters, prepare
from environment import SurfaceExposure
from weather.series import HOUR, WeatherSeries, fill_tail


def test_inverted_curves_integral_and_modes():
    curves, audit = load_curves(SOURCE)
    assert len(curves) == 8
    for name, curve in curves.items():
        row = audit[name]
        assert abs(row["header_heat_mj_m3"] - row["record_heat_mj_m3"]) < .055
        assert row["record_end_h"] == pytest.approx(240.333 if name.endswith("SS") else 163.)
        assert curve.rate(-1) == curve.rate(0) == 0
        assert curve.rate(curve.age_s[-1] + curve.tail_s) == pytest.approx(curve.source_w_m3[-1] / np.e)
    assert curves["M1_22A"].rate(3600) == pytest.approx(9.41/2)


def test_exposed_surface_25mm_and_internal_face_after_pour():
    # En estado estacionario, la reconstrucción sobre un perfil lineal es exacta.
    for dx in (.25, .125):
        # Campo lineal de pendiente 20 K/m y cara a 30 °C con k=2 y h=4.
        assert temperature_at_depth(30+20*dx/2,20,1/4,dx/4,.025,dx/2) == pytest.approx(30.5)
    shape = (2,1,2)
    concrete = np.ones(shape,bool)
    active = np.array([[[True,False]],[[True,False]]])
    boundary = SurfaceExposure(air_c=10,h_w_m2k=8)
    def config(mask):
        return Parameters(shape,(.5,.25,.5),2,2400,900,10,60,
                          {"z+":boundary},active=mask,exposed=boundary)
    monitor = CriticalTemperatures(concrete,[0,0,0],[.25,.25,.25])
    monitor.observe(0,np.full(shape,30.),active,prepare(config(active)))
    assert monitor.delta["surface"]["face"] == "z+"
    assert monitor.delta["surface"]["xyz_m"][2] == pytest.approx(.225)
    assert monitor.delta["profile_mm_c"][1] == [.025 * 1000, monitor.delta["surface"]["value_c"]]
    monitor.observe(1,np.full(shape,40.),concrete,prepare(config(concrete)))
    assert monitor.delta["surface"]["cell"][2] == 1
    assert monitor.delta["surface"]["xyz_m"][2] == pytest.approx(.475)


def test_schedule_and_weighted_union():
    plan = {"id":"A","start_h":[3,12]}
    cfg = {"pump_count":1,"flow_m3_h_per_pump":40,"minimum_wait_h":5}
    rows = schedule(plan,cfg,[160,40])
    assert rows[-1]["finish_h"] == 13
    assert sum(r["duration_h"] for r in rows) == 5
    with pytest.raises(ValueError,match="espera"):
        schedule({"id":"A","start_h":[3,11]},cfg,[160,40])
    def outcome(name,t,d,weight):
        peaks = {"tmax":{"value_c":t},"delta":{"value_c":d}}
        return {"curve":name,"climate":{"id":"central"},"weight":weight,
                "sensitivity_weight":weight,"horizon_open":False,"baseline":peaks,**peaks}
    results = [outcome("M1",70,20,.95),outcome("M2",70.001,20.001,.05)]
    computed = compare(plan,results)
    assert computed["prob_tmax"] == computed["prob_delta"] == computed["prob_joint"] == .05
    assert computed["feasible"]
    results[0]["tmax"]["value_c"] += .001
    assert not compare(plan,results)["feasible"]


def test_progressive_activation_uses_each_level_volume():
    shape = (4, 2, 3)
    concrete = np.zeros(shape, bool)
    concrete[:, :, 1] = True
    concrete[:2, :, 2] = True
    model = {"grid":{"concrete":concrete},"origin_m":np.zeros(3),
             "p":SimpleNamespace(shape=shape,spacing_m=np.ones(3),lengths_m=shape)}
    plan = {"fractions":[0,1],"schedule":[{"layer":1,"start_h":3,"duration_h":6}]}
    result = progressive_plan(model,plan,{"placement_c":20})
    assert np.all(result.start_s[:,:,1] == 5*3600)
    assert np.all(result.start_s[:2,:,2] == 8*3600)
    assert np.isinf(result.start_s[:,:,0]).all()
    assert np.all(result.placement_c[concrete] == 20)


def test_forecast_trailing_nulls_use_last_complete_daily_cycle():
    air = np.r_[np.arange(48) % 24, [np.nan]*48]
    series = WeatherSeries(np.arange(96)*HOUR, air, air, air, origin=["ensemble"]*96)
    trimmed = trim_missing_forecast_edges(series)
    assert trimmed.end_s == 47*HOUR
    filled = fill_tail(trimmed,0,4)
    assert filled.origin[47:49] == ["ensemble","persistencia"]
    np.testing.assert_equal(filled.air_c[48:72],np.arange(24))


def test_weather_block_reuses_coherent_consecutive_hours():
    time = np.arange(100)
    series = WeatherSeries(time*HOUR, time, time*.1, time*2, origin=["ensemble"]*100)
    filled = fill_tail(series, 0, 8, method="bloque72")
    assert filled.origin[99:102] == ["ensemble", "bloque72", "bloque72"]
    np.testing.assert_equal(filled.air_c[100:172], time[-72:])
    np.testing.assert_allclose(filled.wind_10m_m_s, filled.air_c*.1)
    np.testing.assert_equal(filled.shortwave_w_m2, filled.air_c*2)
    assert filled.air_c[172] == time[-72]


def test_late_pour_can_extend_with_stable_global_maximum():
    history = {hour: {"time_h": hour, "tmax_c": 60, "delta_c": 18,
                       "pour_tmax_c": [60, 50 if hour < 312 else 51]}
               for hour in range(288, 337)}
    assert temperature_rising(history, 336)
    history[311]["pour_tmax_c"][1] = 51
    assert not temperature_rising(history, 336)


def test_weather_stress_uses_omitted_members_without_changing_weights():
    rows = [{"id": str(i), "member": str(i), "weight": 1/3,
             "air_p10_c": i, "wind_on_cold_hours_m_s": 10-i,
             "mean_forecast_air_c": i, "sun_mean_w_m2": i}
            for i in range(7)]
    main = rows[1:4]
    stress = weather_sensitivity(main, rows)
    assert [row["member"] for row in stress] == ["0", "6", "2"]
    assert stress[-1]["tail_method"] == "bloque72"
    assert sum(row["weight"] for row in stress) == 0
    assert sum(row["weight"] for row in main) == 1
