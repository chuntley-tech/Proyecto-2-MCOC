from pathlib import Path
import json
import math

import ifcopenshell
import numpy as np
import pytest

from scripts.create_ifc import create_model
from scripts.foundation_geometry import geometry_parts
from scripts.inspect_ifc import compare_reports, inspect_model


CONFIG = Path(__file__).resolve().parents[1] / "config" / "case_g8.json"


def test_generated_ifc_geometry_and_properties(tmp_path):
    path = tmp_path / "base.ifc"
    create_model(CONFIG, path)
    report = inspect_model(path)
    assert report["schema"] == "IFC4"
    assert report["validation_errors"] == 0
    assert report["length_unit_scale_to_m"] == 1
    footings = sorted(report["footings"], key=lambda f: f["tag"])
    assert len(footings) == 3
    assert len({f["guid"] for f in footings}) == 3
    assert len({f["name"] for f in footings}) == 3
    for index, footing in enumerate(footings):
        assert footing["tag"] == f"G8-BASE-{index + 1:02d}"
        expected_width = 7 if index == 2 else 18
        # Las curvas IFC se triangulan para medir: tolerancia de 2 mm en XY.
        np.testing.assert_allclose(footing["dimensions_m"], [expected_width, expected_width, 1.1], atol=.002)
        assert footing["volume_m3"] > 0
        margin = 5.5 if index == 2 else 0
        np.testing.assert_allclose(footing["bounds_min_m"], [margin, margin, index * 1.1], atol=.002)
        np.testing.assert_allclose(footing["bounds_max_m"], [18 - margin, 18 - margin, (index + 1) * 1.1], atol=.002)
        assert len(footing["guid"]) == 22
        assert footing["material"].startswith("Hormigón")
        properties = footing["properties"]["MCOC_InitialModel"]
        np.testing.assert_allclose(properties["Height_m"], 1.1, atol=1e-8)
        assert properties["ObjectID"] == footing["tag"]
    # Los componentes ocupan intervalos verticales contiguos, sin solaparse.
    for lower, upper in zip(footings, footings[1:]):
        np.testing.assert_allclose(lower["bounds_max_m"][2], upper["bounds_min_m"][2], atol=1e-8)
    # Octágono obtenido cortando cuatro triángulos al cuadrado de 18 m.
    octagon_area = 18**2 - 2 * (9 - 3.728)**2
    np.testing.assert_allclose(footings[0]["volume_m3"], octagon_area * 1.1, atol=1e-8)
    np.testing.assert_allclose(footings[2]["volume_m3"], math.pi * 3.5**2 * 1.1, rtol=.001)
    assert math.pi * 3.5**2 * 1.1 < footings[1]["volume_m3"] < octagon_area * 1.1
    model = ifcopenshell.open(str(path))
    circles = model.by_type("IfcCircleProfileDef")
    assert len(circles) == 1
    assert circles[0].Radius == 3.5


def test_saved_model_matches_the_three_component_generator(tmp_path):
    generated = tmp_path / "base.ifc"
    create_model(CONFIG, generated)
    saved = CONFIG.parents[1] / "models" / "g8_base.ifc"
    assert compare_reports(inspect_model(saved), inspect_model(generated)) == []


def test_transition_is_closed_and_matches_end_sections():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))["geometry"]
    part = geometry_parts(config)[1]
    vertices, faces = part["vertices"], part["faces"]
    n = len(vertices) // 2
    np.testing.assert_allclose(np.linalg.norm(vertices[n:, :2], axis=1), 3.5)
    np.testing.assert_allclose(vertices[:n, 2], 0)
    np.testing.assert_allclose(vertices[n:, 2], 1.1)
    assert np.max(np.abs(vertices[:n, :2])) == 9
    edges = {}
    for face in faces:
        for a, b in zip(face, list(face[1:]) + [face[0]]):
            edges[(a, b)] = edges.get((a, b), 0) + 1
    # Cada arista tiene exactamente una cara por lado y sentidos opuestos.
    assert all(count == 1 and edges.get((b, a)) == 1 for (a, b), count in edges.items())


@pytest.mark.parametrize("change", [
    {"cylinder_height_m": 2}, {"cylinder_diameter_m": 20},
    {"octagon_corner_coordinate_m": 10}, {"transition_edge_segments": 1},
    {"base_height_m": float("nan")}
])
def test_inconsistent_geometry_is_rejected(change):
    geometry = json.loads(CONFIG.read_text(encoding="utf-8"))["geometry"]
    with pytest.raises(ValueError):
        geometry_parts(geometry | change)
