"""Pruebas del muestreo, intervalos exactos y repetibilidad térmica del lote final."""

from dataclasses import replace
from math import comb

import numpy as np
import pytest

from scripts import final_campaign, final_mc, final_mc_refinement, monte_carlo
from thermal3d.hydration import load_curves
from weather.series import synthetic_series


def test_clopper_pearson_uses_integer_failures_and_exact_tails():
    assert final_mc.clopper_pearson(0,100) == pytest.approx([0,1-.025**.01],abs=1e-12)
    assert final_mc.clopper_pearson(100,100) == pytest.approx([.025**.01,1],abs=1e-12)
    lo, hi = final_mc.clopper_pearson(5,100)
    mass = lambda p,i: comb(100,i)*p**i*(1-p)**(100-i)
    assert sum(mass(lo,i) for i in range(5,101)) == pytest.approx(.025,abs=1e-12)
    assert sum(mass(hi,i) for i in range(6)) == pytest.approx(.025,abs=1e-12)
    data = [{"tmax":{"value_c":t},"delta":{"value_c":d},"horizon_open":False}
            for t,d in [(70,20),(71,21),(69,21),(72,20)]]
    scores = final_mc.metrics(data)
    assert scores["tmax"]["failures"] == scores["delta"]["failures"] == 2
    assert scores["joint"]["failures"] == 3


def test_seed_reproduces_samples_and_metrics(monkeypatch):
    settings = monte_carlo.read_json(final_mc.CONFIG)
    env = monte_carlo.read_json(final_campaign.ROOT/"config/environment_g8.json")
    weather = replace(synthetic_series(0,days=2),snapshot={"sha256":"synthetic-test"})
    geometry = (np.ones((3,3,3),dtype=int),np.array([.5,.5,.55]),np.zeros(3),"ifc")
    monkeypatch.setattr(final_campaign,"make_weather",lambda *args:(weather,0))
    monkeypatch.setattr(final_campaign,"voxels",lambda mesh:geometry)
    plan = {"id":"P","placement_c":16,"fractions":[0,1],"strip_h":1,"top_remove_h":2,
            "side_blanket":True,"duration_h":.2,
            "schedule":[{"layer":1,"start_h":0,"duration_h":.2}]}
    config = {"plans":[plan],"hours":2,"max_hours":3,"placement_c":16,"activation_energy_j_mol":0,
              "offset_h":2,"tail_h":24,"mix":settings["mix"]}
    args = (settings,["_member01","_member02"],["M1_SS","M4_SS"])
    a = final_mc.draws(*args,2,87)
    b = final_mc.draws(*args,2,87)
    assert a == b and a == final_mc.draws(*args,100,87)[:2]
    assert a != final_mc.draws(*args,2,88)
    solver = final_campaign.solve_construction
    integrated = []

    def capture_integral(params, schedule, hydration, **kwargs):
        integrated.append(np.trapezoid(hydration.source_w_m3,hydration.age_s))
        return solver(params,schedule,hydration,**kwargs)

    monkeypatch.setattr(final_campaign,"solve_construction",capture_integral)
    first = final_campaign.simulate(final_mc._job(plan,a[0],settings),config,env)
    second = final_campaign.simulate(final_mc._job(plan,b[0],settings),config,env)
    assert {k:v for k,v in first.items() if k!="run_seconds"} == {
        k:v for k,v in second.items() if k!="run_seconds"}
    assert first["tmax"] != final_campaign.simulate(final_mc._job(plan,a[1],settings),config,env)["tmax"]
    curves, _ = load_curves(final_campaign.SOURCE,offset_h=2,tail_h=24)
    for realization,result in zip([a[0],b[0],a[1]],integrated,strict=True):
        curve = curves[realization["curve"]]
        assert result == pytest.approx(np.trapezoid(curve.source_w_m3,curve.age_s)*realization["heat_factor"])


def test_control_is_part_of_reproducible_weather_draws():
    settings = monte_carlo.read_json(final_mc.CONFIG)
    numbered = [f"_member{i:02}" for i in range(1,31)]
    old = final_mc.draws(settings,numbered,["M4_SS"],200,settings["seed"])
    new = final_mc.draws(settings,["",*numbered],["M4_SS"],200,settings["seed"])
    assert any(not row["member"] for row in new)
    for a,b in zip(old,new,strict=True):
        assert a == {**b,"member":a["member"]}
        if b["member"]:
            assert a == b


def test_volume_partition_and_richardson():
    unequal = np.zeros((3,3,4))
    unequal[:,:,:2] = 1
    unequal[:2,:,2:] = 1
    cuts = final_mc.equal_volume_fractions((unequal,None,None,None))
    volumes = np.interp(cuts,np.arange(5)/4,[0,9,18,24,30])
    assert volumes == pytest.approx([0,10,20,30])
    fit = final_mc_refinement.richardson([24.,21.,20.25])
    assert fit == pytest.approx({"order":2.,"extrapolated_c":20.})
    assert final_mc_refinement.richardson([22.,20.,22.])["extrapolated_c"] is None


def test_protection_mc_preserves_s7_nominal_and_uses_independent_seed(tmp_path, monkeypatch):
    settings = final_mc.read_settings(final_mc.CONFIG.with_name("monte_carlo_proteccion_g8.json"))
    monkeypatch.setattr(final_campaign,"resolve_campaign",lambda config:config)
    monkeypatch.setattr(final_mc,"complete_members",lambda config,hours: (["","_member01"],165,[]))
    monkeypatch.setattr(final_campaign,"weather_snapshot",lambda folder:({"sha256":"clima"},{}))
    monkeypatch.setattr(final_campaign,"voxels",lambda mesh:(None,None,None,"ifc"))
    main, confirm = tmp_path/"main", tmp_path/"confirm"
    assert final_mc.prepare(main,settings,"sample",size=3)==3
    assert final_mc.prepare(confirm,{**settings,"confirm_ids":["S7"]},"confirm",size=3)==3
    first = monte_carlo.read_json(main/"manifest.json")
    second = monte_carlo.read_json(confirm/"manifest.json")
    assert first["config"]["max_hours"]==2640
    assert first["config"]["plans"][0]["placement_c"]==16
    assert {row["plan"] for row in first["jobs"]}=={"S7"}
    assert all(14 <= row["placement_c"] <= 18 for row in first["jobs"])
    assert first["seed"]!=second["seed"] and first["jobs"]!=second["jobs"]
