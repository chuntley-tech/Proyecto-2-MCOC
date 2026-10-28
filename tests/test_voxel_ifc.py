"""IFC real guardado → máscara, incluyendo cambios geométricos y unidades."""

from pathlib import Path

import ifcopenshell
import ifcopenshell.util.unit
import numpy as np
import pytest

from thermal3d.voxel import Mesh, inside_mesh, load_ifc_meshes, validate_mesh, voxelize

ROOT = Path(__file__).resolve().parents[1]


def cube():
    vertices = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]], dtype=float)
    faces = np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
                      [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
    return Mesh("synthetic", "Cubo sintético", vertices, faces, 1.0)


@pytest.fixture(scope="module")
def actual():
    return load_ifc_meshes(ROOT/"models/g8_base.ifc")


def test_closed_cube_centers_and_exact_volume():
    mesh = cube()
    validate_mesh(mesh.vertices, mesh.faces)
    grid = voxelize([mesh], (0.2, 0.25, 0.5))
    assert grid.component.shape == (5, 4, 2)
    assert grid.active.all()
    assert grid.report["voxel_volume_m3"] == 1.0
    np.testing.assert_array_equal(inside_mesh(np.array([-0.5, 0.5, 1.5]), np.array([0.5]), np.array([0.5]), mesh)[:, 0, 0], [False, True, False])


def test_current_ifc_components_volume_and_provenance(actual):
    meshes, source = actual
    grid = voxelize(meshes, (0.5, 0.5, 0.55), source)
    assert len(meshes) == 3
    assert set(np.unique(grid.component)) == {0, 1, 2, 3}
    assert grid.report["relative_volume_error"] < 0.01  # Geometría escalonada gruesa; error medido 0.00462.
    assert len(grid.report["ifc_input"]["sha256"]) == 64
    assert grid.lengths_m[2] == pytest.approx(3.3)


def test_saved_geometry_change_updates_grid_without_json(tmp_path, actual):
    model = ifcopenshell.open(str(ROOT/"models/g8_base.ifc"))
    cylinder = next(e for e in model.by_type("IfcFooting") if e.Tag == "G8-BASE-03")
    cylinder.Representation.Representations[0].Items[0].Depth = 1.3
    copy = tmp_path/"edited.ifc"
    model.write(str(copy))
    meshes, source = load_ifc_meshes(copy)
    grid = voxelize(meshes, (0.5, 0.5, 0.25), source)
    assert grid.lengths_m[2] == pytest.approx(3.5)
    assert source["sha256"] != actual[1]["sha256"]
    assert grid.component.shape[2] == 14


def test_ifc_units_converted_to_metres(tmp_path, actual):
    model = ifcopenshell.open(str(ROOT/"models/g8_base.ifc"))
    converted = ifcopenshell.util.unit.convert_file_length_units(model, "MILLIMETRE")
    path = tmp_path/"millimetres.ifc"
    converted.write(str(path))
    meshes, source = load_ifc_meshes(path)
    grid = voxelize(meshes, (0.5, 0.5, 0.55), source)
    baseline = voxelize(actual[0], (0.5, 0.5, 0.55), actual[1])
    np.testing.assert_array_equal(grid.component, baseline.component)
    # Conversión SI: solo tolerancia numérica de la transformación de unidades.
    np.testing.assert_allclose(grid.lengths_m, baseline.lengths_m, atol=8e-15, rtol=0)


def test_translation_preserves_mask_and_tracks_origin():
    mesh = cube()
    shifted = Mesh(mesh.guid, mesh.name, mesh.vertices+np.array([5, 8, 3]), mesh.faces, 1.0)
    grid = voxelize([shifted], 0.25)
    np.testing.assert_array_equal(grid.origin_m, [5, 8, 3])
    assert grid.active.all()


def test_open_mesh_and_overlapping_components_rejected():
    mesh = cube()
    with pytest.raises(ValueError, match="cerrada"):
        validate_mesh(mesh.vertices, mesh.faces[:-1])
    with pytest.raises(ValueError, match="Solapamiento"):
        voxelize([mesh, mesh], 0.25)


@pytest.mark.parametrize("spacing", [0, -1, float("nan"), float("inf")])
def test_invalid_resolution_rejected(spacing):
    with pytest.raises(ValueError):
        voxelize([cube()], spacing)
