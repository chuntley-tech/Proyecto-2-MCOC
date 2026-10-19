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
    footings = sorted(report["footings"], key=lambda f: f["tag"])
    assert len(footings) == 3
    assert len({f["guid"] for f in footings}) == 3
    assert len({f["name"] for f in footings}) == 3
    for index, footing in enumerate(footings):
        assert footing["tag"] == f"G8-BASE-{index + 1:02d}"
        np.testing.assert_allclose(footing["dimensions_m"], [18, 18, 1.1], atol=1e-8)
        np.testing.assert_allclose(footing["volume_m3"], 356.4, atol=1e-8)
        np.testing.assert_allclose(footing["bounds_min_m"], [0, 0, index * 1.1], atol=1e-8)
        np.testing.assert_allclose(footing["bounds_max_m"], [18, 18, (index + 1) * 1.1], atol=1e-8)
        assert len(footing["guid"]) == 22
        assert footing["material"].startswith("Hormigón")
        properties = footing["properties"]["MCOC_InitialModel"]
        np.testing.assert_allclose(properties["Height_m"], 1.1, atol=1e-8)
        assert properties["ObjectID"] == footing["tag"]
    # Contacto entre capas sin huecos ni solapamiento y volumen global conservado.
    for lower, upper in zip(footings, footings[1:]):
        np.testing.assert_allclose(lower["bounds_max_m"][2], upper["bounds_min_m"][2], atol=1e-8)
    np.testing.assert_allclose(sum(f["volume_m3"] for f in footings), 1069.2, atol=1e-8)
