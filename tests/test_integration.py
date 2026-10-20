"""Regresiones de integración: conservar el caso principal y rechazar datos inválidos."""

from copy import deepcopy
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element
import numpy as np
import pytest

from scripts.create_ifc import create_model
from scripts.inspect_ifc import compare_reports, inspect_model
from thermal1d.case import case_from_config
from thermal1d.solver import Dirichlet, Parameters, Robin, solve

ROOT = Path(__file__).resolve().parents[1]


def test_main_model_survives_zip_integration_and_detects_saved_changes(tmp_path):
    original, edited = tmp_path / "main.ifc", tmp_path / "edited.ifc"
    create_model(ROOT / "config/case_g8.json", original)
    before = inspect_model(original)
    assert before["element_count"] == 3
    np.testing.assert_allclose(before["dimensions_m"], [18, 18, 3.3])
    model = ifcopenshell.open(str(original))
    element = next(e for e in model.by_type("IfcFooting") if e.Tag == "G8-BASE-02")
    element.Name = "Transición renombrada"
    pset = model.by_id(ifcopenshell.util.element.get_psets(element)["MCOC_InitialModel"]["id"])
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={"GeometryStatus": "Prueba de cambio guardado"})
    model.write(str(edited))
    after = inspect_model(edited)
    assert after["validation_errors"] == 0
    changes = compare_reports(before, after)
    assert any("name" in c and "Transición renombrada" in c for c in changes)
    assert any("GeometryStatus" in c for c in changes)
    assert not any("eliminado" in c or "nuevo" in c for c in changes)


@pytest.mark.parametrize("bad", [
    {"check_stability": "false"},
    {"initial": {"type": "profile", "z_m": [0, float("nan"), 3.3], "temperature_c": [20, 30, 20]}},
    {"initial": {"type": "profile", "z_m": [1, 2], "temperature_c": [20, 30]}},
    {"top": {"type": "robin", "h_w_m2k": 10, "ambient_c": {"mean_c": 20, "period_h": float("nan")}}},
])
def test_malformed_case_is_rejected(bad):
    config = json.loads((ROOT / "config/case_g8.json").read_text(encoding="utf-8"))
    config.update(deepcopy(bad))
    with pytest.raises(ValueError):
        case_from_config(config)


def params(**overrides):
    values = dict(length_m=1., nodes=11, conductivity_w_mk=1., density_kg_m3=1.,
                  specific_heat_j_kgk=1., dt_s=.001, duration_s=.0020000000001,
                  bottom=Dirichlet(20.), top=Dirichlet(20.))
    return Parameters(**(values | overrides))


def test_fractional_final_step_is_not_silently_lengthened():
    p = params()
    result = solve(p, np.full(p.nodes, 20.))
    assert len(result.time_s) == 4
    assert result.time_s[-1] == p.duration_s
    assert np.max(np.diff(result.time_s)) <= p.dt_s * (1 + 1e-12)


@pytest.mark.parametrize("overrides", [
    {"source_w_m3": lambda t: float("nan")},
    {"top": Robin(1., lambda t: float("inf"))}
])
def test_nonfinite_time_functions_are_rejected(overrides):
    with pytest.raises(ValueError, match="no finita"):
        solve(params(**overrides), np.full(11, 20.))
