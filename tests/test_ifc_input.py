"""El solver debe responder al IFC guardado, sin reescribir el JSON."""

import hashlib
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element
import ifcopenshell.util.unit
import numpy as np
import pytest

from scripts.create_ifc import create_model
from scripts.run_case import main
from thermal1d.case import load_case
from thermal1d.solver import solve

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/case_g8.json"


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "copy.ifc"
    create_model(CONFIG, path)
    return path


def cylinder(model):
    return next(e for e in model.by_type("IfcFooting") if e.Tag == "G8-BASE-03")


def change_thermal(model, name, value):
    pset_id = ifcopenshell.util.element.get_psets(cylinder(model))["MCOC_Thermal1D"]["id"]
    ifcopenshell.api.run("pset.edit_pset", model, pset=model.by_id(pset_id), properties={name: value})


def test_height_comes_from_saved_geometry_not_text_properties(source):
    original_json = CONFIG.read_bytes()
    baseline = load_case(CONFIG, ifc_path=source)
    model = ifcopenshell.open(str(source))
    footing = cylinder(model)
    solid = footing.Representation.Representations[0].Items[0]
    solid.Depth = 1.6  # z superior pasa a 3.80 m; Height_m informativo sigue en 1.10.
    footing.Name = "Cilindro renombrado en Bonsai"
    model.write(str(source))
    changed = load_case(CONFIG, ifc_path=source)
    assert changed.params.length_m == pytest.approx(3.8)
    assert changed.x_m[-1] == pytest.approx(3.8)
    assert changed.ifc_input["sha256"] != baseline.ifc_input["sha256"]
    assert CONFIG.read_bytes() == original_json
    old = solve(baseline.params, baseline.initial_c, save_every=10**6)
    new = solve(changed.params, changed.initial_c, save_every=10**6)
    assert new.temperature_c[-1, 33] > old.temperature_c[-1, 33]


def test_material_property_changes_the_solution(source):
    baseline = load_case(CONFIG, ifc_path=source)
    model = ifcopenshell.open(str(source))
    change_thermal(model, "Conductivity_W_mK", 1.1)
    model.write(str(source))
    changed = load_case(CONFIG, ifc_path=source)
    assert changed.params.conductivity_w_mk == 1.1
    assert changed.params.alpha_m2_s == pytest.approx(baseline.params.alpha_m2_s / 2)
    old = solve(baseline.params, baseline.initial_c, save_every=10**6)
    new = solve(changed.params, changed.initial_c, save_every=10**6)
    assert new.temperature_c[-1, 33] > old.temperature_c[-1, 33]


def test_ifc_properties_win_and_json_mode_is_explicit(source):
    case = load_case(CONFIG, ["thermal.length_m=4", "thermal.conductivity_w_mk=1"], ifc_path=source)
    assert case.params.length_m == pytest.approx(3.3)
    assert case.params.conductivity_w_mk == 2.2
    manual = load_case(CONFIG, ["thermal.length_m=4", "thermal.conductivity_w_mk=1"], use_ifc=False)
    assert manual.params.length_m == 4
    assert manual.params.conductivity_w_mk == 1
    assert manual.ifc_input is None


def test_millimetre_ifc_is_read_in_metres(source):
    model = ifcopenshell.open(str(source))
    converted = ifcopenshell.util.unit.convert_file_length_units(model, "MILLIMETRE")
    converted.write(str(source))
    case = load_case(CONFIG, ifc_path=source)
    assert case.params.length_m == pytest.approx(3.3)


def test_json_relative_ifc_path_works_outside_project(source, tmp_path, monkeypatch):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["ifc"]["path"] = source.name
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps(config), encoding="utf-8")
    folder = tmp_path / "another_directory"
    folder.mkdir()
    monkeypatch.chdir(folder)
    assert load_case(case_path).params.length_m == pytest.approx(3.3)


@pytest.mark.parametrize("edit", ["missing_guid", "missing_property", "negative_property", "gap", "unstable"])
def test_inconsistent_ifc_does_not_silently_fall_back_to_json(source, edit):
    model = ifcopenshell.open(str(source))
    footing = cylinder(model)
    if edit == "missing_guid":
        footing.GlobalId = ifcopenshell.guid.new()
    elif edit == "missing_property":
        change_thermal(model, "Conductivity_W_mK", None)
    elif edit == "negative_property":
        change_thermal(model, "Density_kg_m3", -1.)
    elif edit == "unstable":
        change_thermal(model, "Conductivity_W_mK", 22.)
    else:
        placement = np.eye(4)
        placement[:3, 3] = [9, 9, 2.5]
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=footing, matrix=placement)
    model.write(str(source))
    with pytest.raises(ValueError):
        load_case(CONFIG, ifc_path=source)


def test_width_only_is_recorded_but_does_not_change_1d_temperature(source):
    baseline = load_case(CONFIG, ifc_path=source)
    model = ifcopenshell.open(str(source))
    cylinder(model).Representation.Representations[0].Items[0].SweptArea.Radius = 3.0
    model.write(str(source))
    changed = load_case(CONFIG, ifc_path=source)
    assert changed.params == baseline.params
    assert changed.ifc_input["sha256"] != baseline.ifc_input["sha256"]


def test_cli_exports_actual_ifc_inputs(source, tmp_path):
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    summary = main(["--ifc", str(source), "--output", str(tmp_path / "out")])
    assert summary["ifc_input"]["sha256"] == before
    assert summary["parameters"]["length_m"] == pytest.approx(3.3)
    assert source.read_bytes() and hashlib.sha256(source.read_bytes()).hexdigest() == before
