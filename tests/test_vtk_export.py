"""Exportación VTK (.vti/.pvd) escrita sin PyVista: estructura y lectura de vuelta."""

import numpy as np
import pytest

from thermal3d.vtk_export import read_vti, write_pvd, write_vti


def test_vti_round_trip_keeps_values_order_and_geometry(tmp_path):
    shape = (3, 4, 5)
    temperature = np.arange(np.prod(shape), dtype=float).reshape(shape) / 7
    temperature[0, 0, 0] = np.nan                      # celda inactiva
    zone = (temperature > 3).astype(np.int8)
    path = write_vti(tmp_path / "t.vti", {"temperature": temperature.astype(np.float32), "zone": zone,
                                          "active": np.isfinite(temperature)},
                     (0.25, 0.25, 0.275), (-1.5, -1.5, -2.2), {"TimeValue": 12.0})
    data = read_vti(path)
    assert data["shape"] == shape
    assert data["spacing"] == [0.25, 0.25, 0.275] and data["origin"] == [-1.5, -1.5, -2.2]
    assert data["fields"]["TimeValue"] == 12.0
    np.testing.assert_array_equal(data["cells"]["zone"], zone)
    np.testing.assert_allclose(data["cells"]["temperature"], temperature.astype(np.float32), equal_nan=True)
    assert data["cells"]["active"].dtype == np.uint8
    header = path.read_bytes()[:600].decode("utf-8", errors="replace")
    assert 'WholeExtent="0 3 0 4 0 5"' in header          # puntos = celdas + 1
    assert "np.float" not in header


def test_vti_x_varies_fastest_like_vtk(tmp_path):
    field = np.zeros((2, 3, 1))
    field[1, 0, 0] = 5.0                               # segunda celda en el orden de VTK
    path = write_vti(tmp_path / "o.vti", {"f": field}, (1.0, 1.0, 1.0))
    raw = path.read_bytes()
    start = raw.index(b"_", raw.index(b"<AppendedData")) + 1
    values = np.frombuffer(raw[start + 4:start + 4 + 6 * 8], dtype="<f8")
    assert values[1] == 5.0


def test_two_dimensional_fields_and_mismatched_shapes(tmp_path):
    data = read_vti(write_vti(tmp_path / "s.vti", {"f": np.ones((4, 3))}, (0.5, 0.5)))
    assert data["shape"] == (4, 3, 1)
    with pytest.raises(ValueError):
        write_vti(tmp_path / "bad.vti", {"a": np.ones((2, 2, 2)), "b": np.ones((2, 2, 3))}, (1, 1, 1))


def test_pvd_lists_frames_with_times(tmp_path):
    path = write_pvd(tmp_path / "serie.pvd", [(0.0, "vtk/temperature_0000.vti"), (6.0, "vtk/temperature_0001.vti")])
    text = path.read_text(encoding="utf-8")
    assert text.count("<DataSet") == 2 and 'timestep="6.0"' in text and 'type="Collection"' in text
