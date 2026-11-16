"""Pipeline E11 completo con un snapshot FICTICIO (forma de Open-Meteo, valores inventados)."""

import argparse
import json
import shutil
import subprocess

import numpy as np
import pytest

from scripts import view_3d, weather_3d
from thermal3d.vtk_export import read_vti
from thermal3d.solver import prepare
from weather.series import HOUR, synthetic_series
from weather.open_meteo import build_request
from weather.snapshots import save_snapshot

from test_weather import fake_payload, raw


def _config(tmp_path):
    config = json.loads((weather_3d.ROOT_DIR / "config" / "environment_g8.json").read_text(encoding="utf-8"))
    config["weather"]["snapshot_root"] = str(tmp_path / "weather")
    return config


def _args(tmp_path, **changes):
    values = dict(snapshot=None, start=None, hours=12.0, every=6.0, max_dt=900.0, coarsen=2, no_hydration=False,
                  synthetic=False, out=str(tmp_path / "out"))
    values.update(changes)
    return argparse.Namespace(**values)


def test_snapshot_feeds_boundaries_and_exports_vtk(tmp_path):
    request = build_request("forecast", -41.222539, -73.295603)
    folder = save_snapshot(raw(fake_payload(first="2026-11-11T00:00", hours=96)), request,
                           root=tmp_path / "weather", retrieved_at="2026-11-11T15:20Z")
    out, summary = weather_3d.run(_args(tmp_path, hours=12.1), _config(tmp_path))
    assert summary["weather"]["sha256"] and summary["weather"]["kind"] == "forecast"
    assert summary["simulation"]["start_utc"] == "2026-11-11T16:00Z"     # primera hora después de la descarga
    assert summary["simulation"]["energy_balance_relative"] < 1e-10
    assert summary["simulation"]["dt_s"] <= summary["simulation"]["dt_limit_s"]
    # El aire del borde superior a t = 0 es exactamente el del snapshot a las 16:00 UTC.
    hourly = fake_payload(first="2026-11-11T00:00", hours=96)["hourly"]
    assert summary["boundaries_at_t0"]["top"]["aire_c"] == pytest.approx(hourly["temperature_2m"][16])
    for name in ("clima_snapshot.png", "nucleo_superficie.png", "temperature.pvd", "final.vti", "resumen.json", "visor_e11.json"):
        assert (out / name).exists()
    final = read_vti(out / "final.vti")
    cells = final["cells"]
    core = tuple(summary["core"]["cell"])
    assert cells["zone"][core] == weather_3d.ZONE["nucleo"]
    assert cells["material"][core] == weather_3d.MATERIAL["hormigon"]
    assert np.all(np.isnan(cells["temperature"][cells["material"] == 0]))
    assert np.any(cells["zone"] == weather_3d.ZONE["superficie"])
    assert np.any(cells["zone"] == weather_3d.ZONE["contacto_suelo"])
    assert summary["core"]["depth_to_boundary_m"] == pytest.approx(np.nanmax(cells["depth_to_boundary_m"]))
    viewer = json.loads((out / "visor_e11.json").read_text(encoding="utf-8"))
    assert viewer["times_h"] == pytest.approx([0.0, 6.0, 12.0, 12.1])
    assert len(viewer["boundary_frames"]) == len(viewer["times_h"])
    assert viewer["boundary_frames"][0]["h_w_m2k"] == pytest.approx(summary["boundaries_at_t0"]["top"]["h_w_m2k"])
    assert viewer["boundary_frames"][0]["air_c"] == pytest.approx(hourly["temperature_2m"][16])
    assert viewer["history"]["t_h"][-1] == pytest.approx(12.1)
    assert final["fields"]["TimeValue"] == pytest.approx(12.1)
    # El JSON conserva orden C y redondea la temperatura a 0,001 °C.
    np.testing.assert_allclose(viewer["frames_c"][-1],
                               cells["temperature"].ravel()[viewer["active_indices"]], atol=0.00051, rtol=0)
    node = shutil.which("node")
    if node:
        app = (weather_3d.ROOT_DIR / "web" / "app.js").read_text(encoding="utf-8")
        validator = app[app.index("const e11Planes"):app.index("function e11Current")]
        check = """
const fs = require('node:fs');
const assert = require('node:assert/strict');
const result = JSON.parse(fs.readFileSync(0, 'utf8'));
const validated = validateE11(result);
assert.equal(validated.lookup[result.active_indices[0]], 0);
assert.throws(() => validateE11({...result, frames_c: [[null]]}), /E11/);
"""
        subprocess.run([node, "-e", validator + check], input=json.dumps(viewer),
                       text=True, encoding="utf-8", check=True, timeout=20)
    view_3d.main([str(out)])
    assert list(out.glob("slices_*.png"))


def test_series_shorter_than_simulation_is_refused(tmp_path):
    request = build_request("forecast", -41.222539, -73.295603)
    save_snapshot(raw(fake_payload(first="2026-11-11T00:00", hours=24)), request,
                  root=tmp_path / "weather", retrieved_at="2026-11-11T15:20Z")
    with pytest.raises(ValueError, match="fuera"):
        weather_3d.run(_args(tmp_path, hours=48.0), _config(tmp_path))


def test_snapshot_from_another_location_is_rejected(tmp_path):
    request = build_request("forecast", -41.2, -73.3)
    folder = save_snapshot(raw(fake_payload()), request, root=tmp_path / "weather",
                           retrieved_at="2026-11-11T15:20Z")
    with pytest.raises(ValueError, match="punto meteorológico"):
        weather_3d.load_weather(_args(tmp_path, snapshot=folder), _config(tmp_path))


def test_without_snapshot_explains_how_to_get_one(tmp_path):
    (tmp_path / "weather").mkdir()
    with pytest.raises(LookupError, match="fetch_weather"):
        weather_3d.run(_args(tmp_path), _config(tmp_path))


def test_exposed_and_depth_helpers():
    concrete = np.zeros((5, 5, 5), bool)
    concrete[1:4, 1:4, 1:4] = True
    exposed = weather_3d.touching(concrete, ~concrete)
    assert exposed.sum() == 26 and not exposed[2, 2, 2]
    depth = weather_3d.surface_depth(concrete, exposed, (1.0, 1.0, 1.0))
    assert depth[2, 2, 2] == 1.0 and depth[1, 1, 1] == 0.0


def test_pyvista_surfaces_keep_active_frame_indices():
    pytest.importorskip("pyvista")
    from thermal3d.pyvista_export import export_surfaces

    material = np.zeros((3, 2, 2), dtype=np.uint8)
    material[1:, 0, 0] = 1
    material[0, :, 1] = 2
    spacing = (0.25, 0.5, 0.75)
    origin = (-1, 0.5, -2)
    result = export_surfaces(material, spacing, origin)
    cells = np.argwhere(material > 0)
    for surface in result["surfaces"]:
        vertices = np.asarray(surface["points_m"])
        for face, index in zip(surface["triangles"], surface["frame_indices"]):
            cell = cells[index]
            assert material[tuple(cell)] == surface["material"]
            low = np.array(origin) + cell * spacing
            assert np.all(vertices[face] >= low)
            assert np.all(vertices[face] <= low + spacing)
        assert len(surface["triangles"]) == 20  # Dos voxeles juntos, diez caras expuestas.


def test_progressive_blankets_and_subbase_resistance(tmp_path):
    config = _config(tmp_path)
    config["insulation"]["blanket_stages"] = [[0, .10], [120, .05], [240, 0]]
    config["soil"]["subbase_r_m2k_w"] = 2.5
    geometry = (np.ones((2, 2, 2)), np.array([.5, .5, .55]), np.zeros(3), "test")
    model = weather_3d.build_model(config, synthetic_series(0, days=12), 0, 264, voxels=geometry)
    top, side = model["faces"]["top"], model["faces"]["side"]
    assert top.layers.resistance_at(0) == pytest.approx(.10/.04)
    assert side.layers.resistance_at(0) == pytest.approx(.10/.04 + .018/.13)
    assert side.layers.resistance_at(72*HOUR) == pytest.approx(.10/.04)
    assert side.layers.resistance_at(120*HOUR) == top.layers.resistance_at(120*HOUR) == pytest.approx(.05/.04)
    assert side.layers.resistance_at(240*HOUR) == top.layers.resistance_at(240*HOUR) == 0
    params = model["p"]
    resistance = params.vertical_face_resistance_m2k_w
    assert np.count_nonzero(resistance) == 4
    area = .5*.5
    expected = area / (.55/(2*1.39) + .55/(2*2.2) + 2.5)
    assert prepare(params).gz[resistance > 0] == pytest.approx(np.repeat(expected,4))


def test_central_blanket_uses_thicker_voxel_columns(tmp_path):
    config = _config(tmp_path)
    config["insulation"].update(blanket_stages=[[0,.15],[240,0]], blanket_core_stages=[[0,.05],[240,0]])
    component = np.ones((2,2,4))
    component[1,:,2:] = 0
    geometry = (component, np.array([.5,.5,.55]), np.zeros(3), "test")
    model = weather_3d.build_model(config, synthetic_series(0,days=12), 0, 264, voxels=geometry)
    regions = {region.name: region for region in model["p"].exposed.regions}
    central, edge = regions["superior central"], regions["superior periférica"]
    assert central.cells.sum() == 8 and edge.cells.sum() == 4
    assert central.boundary.layers.resistance_at(0) == pytest.approx(.05/.04)
    assert edge.boundary.layers.resistance_at(0) == pytest.approx(.15/.04)
