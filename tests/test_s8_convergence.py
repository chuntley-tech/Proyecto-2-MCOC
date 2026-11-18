"""Regresiones del ajuste vertical del IFC y del criterio de estabilización."""

import numpy as np
from scripts.converge_s8 import geometry, assess
from scripts.converge_s8 import fixed_protection
from scripts import final_campaign, monte_carlo, weather_3d


def test_aligned_meshes_double_exactly_despite_ifc_roundoff():
    coarse, medium, fine = [geometry(n) for n in (24,48,96)]
    for grid,n in zip((coarse,medium,fine),(24,48,96)):
        assert grid[0].shape == (n,n,n//4)
        np.testing.assert_allclose(1.1/grid[1][2], n/12,atol=1e-6)
    np.testing.assert_allclose(coarse[1],2*medium[1])
    np.testing.assert_allclose(medium[1],2*fine[1])
    assert coarse[3]==medium[3]==fine[3]


def test_stability_target_rejects_previous_s8_sequence():
    assert not assess([15.601996,15.638296,17.048918])["stable_sequence"]
    assert assess([17.4,17.1,17.025])["stable_sequence"]
    assert not assess([18.,17.5,17.25])["stable_sequence"]


def test_ifc_protection_partition_is_independent_of_vertical_cell_count():
    config=monte_carlo.read_json("config/final_g8_s8.json")
    env=monte_carlo.read_json("config/environment_s8.json")
    plan=config["plans"][0]
    env["insulation"].update({key:plan[key] for key in ("blanket_stages","blanket_core_stages")})
    series,start=final_campaign.make_weather(config,"_member23")
    comp,spacing,origin,fingerprint=geometry(24)
    geometries=[(comp,spacing,origin,fingerprint),
                (np.repeat(comp,2,axis=2),spacing/np.array([1,1,2]),origin,fingerprint)]
    sections=[]
    for grid in geometries:
        model=weather_3d.build_model(env,series,start,1,voxels=grid)
        fixed=fixed_protection(model)
        regions={r.name:r for r in fixed["p"].exposed.regions}
        core=regions["superior central"].cells
        outer=regions["superior periférica"].cells
        assert not (core & outer).any()
        np.testing.assert_array_equal(core|outer,model["grid"]["concrete"])
        assert fixed["p"].boundaries["z+"] is fixed["p"].exposed
        sections.append(core.any(axis=2))
    np.testing.assert_array_equal(*sections)
