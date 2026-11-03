"""Presentación de bordes y trazabilidad del último cálculo del visor."""

import json
import shutil
import subprocess

import pytest

from thermal3d.dashboard import ROOT, run_simulation


def run_helpers(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para verificar la lógica del visor")
    source = (ROOT / "web/app.js").read_text(encoding="utf-8")
    helpers = source[source.index("function boundaryFaces("):source.index("async function calculate(")]
    output = subprocess.run(
        [node, "-"], input=helpers + code, text=True, encoding="utf-8",
        capture_output=True, check=True, timeout=10,
    )
    return json.loads(output.stdout)


@pytest.mark.parametrize("dimension,base", [(1, "x−"), (2, "y−"), (3, "z−")])
def test_face_table_assigns_base_to_last_negative_axis(dimension, base):
    result = {"dimension": dimension, "boundary_used": {
        "base": "Adiabático · flujo 0 W/m²", "laterales_y_expuestas": "Dirichlet · 20 °C"}}
    rows = run_helpers("console.log(JSON.stringify(boundaryFaces(" + json.dumps(result) + "))); ")
    assert len(rows) == 2 * dimension
    assert [r["face"] for r in rows if r["condition"].startswith("Adiabático")] == [base]
    assert all(r["condition"] == "Dirichlet · 20 °C" for r in rows if r["face"] != base)


def test_summary_uses_effective_mesh_and_saved_simulation():
    # Ensayo sintético pequeño; no representa mediciones del caso G8.
    result = run_simulation({"mode": "2d", "nodes": 8, "length_x_m": 2,
                             "length_y_m": 1, "duration_days": 0.01,
                             "source_w_m3": 7, "dt_s": None})
    code = "const num=(v,n)=>Number(v).toFixed(n);const r=" + json.dumps(result) + ";"
    code += "console.log(JSON.stringify(simulationSummary(r)));"
    text = run_helpers(code)
    assert "2.000 × 1.000 m" in text
    assert "0.25000 × 0.12500 m" in text
    assert "profundidad 1 m" in text
    assert "Fuente constante = 7.00 W/m³" in text
    assert f"Δt efectivo: {result['stats']['dt_s']:.6f} s (automático)" in text


def test_pending_changes_survive_failure_and_clear_on_revert():
    code = """let data={parameters:{initial_c:20}},busy=false;
let current={initial_c:20},calculatedOptions=JSON.stringify(current);
const options=()=>current,events=[];
const $=()=>({classList:{toggle:(name,hidden)=>events.push(hidden)}});
const state=()=>{};
refreshPendingChanges();
current={initial_c:30};refreshPendingChanges();
// Un fallo no sustituye el último resultado ni su configuración.
refreshPendingChanges();
current={initial_c:20};refreshPendingChanges();
console.log(JSON.stringify({events,temperature:data.parameters.initial_c}));
"""
    actual = run_helpers(code)
    assert actual == {"events": [True, False, False, True], "temperature": 20}
