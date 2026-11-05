"""Contraste Python/HTML portátil con cronograma sintético y superficies móviles."""

import json
import shutil
import subprocess

import numpy as np
import pytest

from scripts.build_dashboard import build_pack
from thermal3d.dashboard import ROOT, run_simulation, validate_options


@pytest.fixture(scope="module")
def pack():
    return build_pack(resolutions=(0.5,))


@pytest.mark.parametrize("boundary,source", [("robin", "cosine"), ("dirichlet", "constant"), ("neumann", "cosine")])
def test_portable_stages_match_python_and_hide_future_concrete(pack, boundary, source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para el contraste portátil")
    rows = [{"start_days": .002+i*.004, "placement_c": 20+i*3} for i in range(3)]
    options = {"construction_mode": "staged", "mode": "fundacion", "resolution_m": .5,
               "pour_count": 3, "pour_schedule": json.dumps(rows), "duration_days": .015,
               "source_type": source, "source_duration_days": .01, "source_w_m3": 100,
               "boundary_type": boundary, "boundary_c": 20, "dt_s": 100}
    python = run_simulation(options)
    json.dumps(python, allow_nan=False)  # Respuesta HTTP/JSON estricta, sin NaN.
    code = "const {runOffline}=require('./web/solver_worker.js');const p=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(runOffline(p.options,p.pack)));"
    output = subprocess.run([node, "-e", code], input=json.dumps({"options": options, "pack": pack}),
                            cwd=ROOT, encoding="utf-8", text=True, capture_output=True, check=True, timeout=30)
    js = json.loads(output.stdout)
    assert js["stats"]["steps"] == python["stats"]["steps"]
    # Mismo reloj de eventos: tolerancia de suma Float64 en segundos.
    np.testing.assert_allclose(js["time_s"], python["time_s"], rtol=0, atol=1e-10)
    a, b = np.asarray(js["frames_c"], float), np.asarray(python["frames_c"], float)
    np.testing.assert_array_equal(np.isnan(a), np.isnan(b))
    # Campos publicados redondeados a 5 decimales: máximo un último dígito.
    np.testing.assert_allclose(a, b, rtol=0, atol=1.01e-5, equal_nan=True)
    assert all(t is None for t in js["frames_c"][0])
    assert js["history"]["mean_c"][0] is None
    assert not js["pour_plan"]["simultaneous"]
    # Integración del reloj por celda, incluidos los ceros previos a colocar.
    np.testing.assert_allclose(js["construction"]["equivalent_age_s"],
                               python["construction"]["equivalent_age_s"], rtol=3e-13, atol=1e-9)
    for a, b in zip(js["source_curve"]["layers"], python["source_curve"]["layers"]):
        np.testing.assert_allclose(a["rate_w_m3"], b["rate_w_m3"], rtol=3e-12, atol=1e-9)
    for name in ("source_heat_in_j", "boundary_heat_in_j", "placement_energy_j"):
        # Reducciones JS y NumPy en miles de celdas; margen de redondeo relativo.
        np.testing.assert_allclose(js["construction"][name], python["construction"][name], rtol=3e-12, atol=1e-6)
    assert python["stats"]["balance_relative_error"] < 1e-12
    assert js["stats"]["balance_relative_error"] < 1e-12
    for row, layer in zip(rows, js["source_curve"]["layers"]):
        assert all(q == 0 for t, q in zip(js["source_curve"]["time_s"], layer["rate_w_m3"]) if t < row["start_days"]*86400)


@pytest.mark.parametrize("schedule", ['null', '[{}]', '[{"start_days":NaN,"placement_c":20}]'])
def test_invalid_schedule_rejected(schedule):
    with pytest.raises(ValueError, match="Cronograma"):
        validate_options({"construction_mode": "staged", "pour_schedule": schedule})


def test_model_masks_unplaced_cells_in_temperature_and_layer_coloring():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para el visor")
    source = (ROOT/"web/app.js").read_text(encoding="utf-8")
    helper = source[source.index("function modelValues("):source.index("function heightProfiles(")]
    code = "let data={frames_c:[[null,20]],pour_plan:{cell_pour_id:[1,2],layers:[{},{}]}},frame=0,layers=false;const pourColorsActive=()=>layers;"
    code += helper + "const temperature=modelValues(),hidden=modelValues(new Set([2]));layers=true;console.log(JSON.stringify([temperature,modelValues(),hidden,modelValues(new Set([2])),data.frames_c[0]]));"
    output = subprocess.run([node, "-"], input=code, encoding="utf-8", text=True, capture_output=True, check=True)
    actual = json.loads(output.stdout)
    assert actual == [[-1e20, 20], [-1e20, .75], [-1e20, -1e20], [-1e20, -1e20], [None, 20]]
