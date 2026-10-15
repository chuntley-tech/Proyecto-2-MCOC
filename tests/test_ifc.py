from pathlib import Path

import numpy as np

from scripts.create_ifc import create_model
from scripts.inspect_ifc import inspect_model


CONFIG = Path(__file__).resolve().parents[1] / "config" / "case_g8.json"


def test_generated_ifc_geometry_and_properties(tmp_path):
    path = tmp_path / "base.ifc"
    create_model(CONFIG, path)
    report = inspect_model(path)
    assert report["schema"] == "IFC4"
    assert report["validation_errors"] == 0
    assert report["length_unit_scale_to_m"] == 1
    assert len(report["footings"]) == 1
    footing = report["footings"][0]
    np.testing.assert_allclose(footing["dimensions_m"], [18, 18, 3.3], atol=1e-8)
    np.testing.assert_allclose(footing["volume_m3"], 1069.2, atol=1e-8)
    assert len(footing["guid"]) == 22
    assert footing["material"].startswith("Hormigón")
    assert footing["properties"]["MCOC_InitialModel"]["Height_m"] == 3.3
