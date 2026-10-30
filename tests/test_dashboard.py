"""Controles del HTML conectados al solver: cambios reales, máscaras y límites."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.serve_dashboard import Handler
from thermal3d.dashboard import run_simulation, validate_options, source_value


def test_pulse_definition_units_peak_and_cutoff():
    o=validate_options({"source_type":"cosine","qmax_w_m3":1000,"source_duration_days":2})
    assert source_value(o,0) == 0
    assert source_value(o,86400) == 1000
    assert source_value(o,172800) == source_value(o,259200) == 0
    assert source_value(o,43200) == pytest.approx(500,abs=1e-12)
    # El paso automático no debe saltarse el pulso por una malla muy gruesa.
    result=run_simulation({"mode":"3d","nodes":8,"length_x_m":20,
        "length_y_m":20,"length_z_m":20,"source_type":"cosine",
        "source_duration_days":0.02,"duration_days":0.04})
    assert result["stats"]["dt_s"] <= 0.02*86400/100


def equilibrium(mode):
    return {"mode": mode, "nodes": 8, "duration_days": 0.01, "initial_c": 20.0,
            "boundary_type": "dirichlet", "boundary_c": 20.0,
            "bottom_type": "dirichlet", "bottom_c": 20.0}


@pytest.mark.parametrize("mode", ["1d", "2d", "3d"])
def test_equilibrium_and_saved_time(mode):
    result = run_simulation(equilibrium(mode))
    values = np.asarray(result["frames_c"])
    np.testing.assert_array_equal(values, 20.0)
    assert result["time_s"][-1] == 864.0
    assert len(result["time_s"]) == len(values) <= 26
    assert result["stats"]["dt_s"] <= result["stats"]["limit_dt_s"]
    json.dumps(result, allow_nan=False)


def test_boundary_control_changes_temperatures():
    cold = equilibrium("2d")
    hot = {**cold, "boundary_c": 40.0}
    assert run_simulation(hot)["history"]["max_c"][-1] > run_simulation(cold)["history"]["max_c"][-1]


def test_source_control_obeys_uniform_energy_balance():
    q, duration = 200.0, 0.01
    result = run_simulation({**equilibrium("3d"), "boundary_type": "neumann", "bottom_type": "neumann",
                             "source_w_m3": q, "duration_days": duration})
    expected = 20+q*duration*86400/(2400*900)
    # El campo visual se redondea explícitamente a 5 decimales; el oráculo vale 20.08 exacto.
    np.testing.assert_allclose(result["frames_c"][-1], expected, rtol=0, atol=1e-14)
    assert result["stats"]["balance_relative_error"] < 1e-14


def test_foundation_comes_from_ifc_and_controls_change_solution():
    options = {"resolution_m": 0.5, "duration_days": 0.1}
    first = run_simulation(options)
    second = run_simulation({**options, "boundary_c": -10.0, "h_w_m2k": 20.0})
    assert len(first["ifc"]["sha256"]) == 64
    assert first["shape"] == [36, 36, 6]
    assert first["stats"]["cells"] == 3528
    assert second["history"]["mean_c"][-1] < first["history"]["mean_c"][-1]
    assert len(first["positions_m"]) == first["stats"]["cells"]


def test_scaled_foundation_changes_physical_grid_and_conserves_reference():
    options={"mode":"fundacion","resolution_m":0.5,"duration_days":0.1}
    original=run_simulation(options)
    scaled=run_simulation({**options,"foundation_geometry":"scaled",
        "foundation_x_m":21.6,"foundation_y_m":14.4,"foundation_height_m":4.95,"pour_count":4})
    np.testing.assert_allclose(scaled["lengths_m"],[21.6,14.4,4.95],rtol=0,atol=1e-14)
    factors=np.array([21.6,14.4,4.95])/original["lengths_m"]
    np.testing.assert_allclose(np.array(scaled["spacing_m"])/original["spacing_m"],factors,rtol=0,atol=1e-14)
    assert scaled["active_indices"] == original["active_indices"]
    assert scaled["ifc"]["sha256"] == original["ifc"]["sha256"]
    assert scaled["history"]["mean_c"][-1] != original["history"]["mean_c"][-1]
    plan=scaled["pour_plan"]
    assert len(plan["layers"]) == 4 and plan["simultaneous"]
    assert len(plan["cell_pour_id"]) == scaled["stats"]["cells"]
    total=sum(row["voxel_volume_m3"] for row in plan["layers"])
    ref=sum(row["voxel_volume_m3"] for row in original["pour_plan"]["layers"])
    # Misma máscara: determinante del escalado respecto de las dimensiones IFC
    # leídas (la triangulación contiene pequeñas diferencias del nominal 3.30 m).
    assert total/ref == pytest.approx(float(np.prod(factors)),rel=1e-14)
    assert sum(row["cells"] for row in plan["layers"]) == scaled["stats"]["cells"]
    assert plan["layers"][0]["z_min_m"] == scaled["origin_m"][2]
    assert plan["layers"][-1]["z_max_m"] == pytest.approx(4.95,abs=1e-14)


def test_pour_count_is_geometric_not_a_fake_construction_sequence():
    options={"mode":"fundacion","resolution_m":0.5,"duration_days":0.01}
    first=run_simulation({**options,"pour_count":1})
    second=run_simulation({**options,"pour_count":5})
    assert first["frames_c"] == second["frames_c"]
    assert first["history"] == second["history"]
    assert len(second["pour_plan"]["layers"]) == 5
    with pytest.raises(ValueError,match="malla más fina"):
        run_simulation({**options,"pour_count":7})


@pytest.mark.parametrize("value",[0,13,1.5,True])
def test_invalid_pour_count_rejected(value):
    with pytest.raises(ValueError,match="vertidas"):
        validate_options({"pour_count":value})


@pytest.mark.parametrize("change", [{"mode":"inventado"}, {"unknown":1}, {"nodes":8.5},
    {"duration_days":float("inf")}, {"conductivity_w_mk":-1}, {"dt_s":-1}, {"initial_c":True}])
def test_invalid_controls_rejected(change):
    with pytest.raises(ValueError):
        validate_options(change)


def test_unstable_time_step_rejected():
    with pytest.raises(ValueError, match="inestable|Estabilidad"):
        run_simulation({**equilibrium("3d"), "dt_s":1000000})


def test_local_server_rejects_foreign_host_and_origin():
    server = SimpleNamespace(server_port=8765)
    valid = SimpleNamespace(server=server, headers={"Host":"127.0.0.1:8765", "Origin":"http://127.0.0.1:8765"})
    assert Handler._local_request(valid)
    foreign = SimpleNamespace(server=server, headers={"Host":"127.0.0.1:8765", "Origin":"https://externo.invalid"})
    assert not Handler._local_request(foreign)
    other = SimpleNamespace(server=server, headers={"Host":"externo.invalid"})
    assert not Handler._local_request(other)
