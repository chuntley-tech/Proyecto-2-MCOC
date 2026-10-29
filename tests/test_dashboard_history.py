"""Curvas de Dirichlet y selección temporal del gráfico, sin simular datos."""

import json
import shutil
import subprocess

import pytest

from thermal3d.dashboard import ROOT, run_simulation


def test_cube_preset_uses_visible_pulse_instead_of_zero_source():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node opcional para comprobar los valores iniciales del visor")
    from thermal3d.dashboard import DEFAULTS
    source=(ROOT/"web/app.js").read_text(encoding="utf-8")
    helper=source[source.index("function casePreset("):source.index("function preset(")]
    code=helper+"console.log(JSON.stringify(casePreset('3d',"+json.dumps(DEFAULTS)+")));"
    output=subprocess.run([node,"-"],input=code,capture_output=True,text=True,check=True,timeout=10)
    options=json.loads(output.stdout)
    assert options["source_type"] == "cosine"
    assert options["qmax_w_m3"] == 1300
    assert options["duration_days"] >= 2*options["source_duration_days"]
    assert options["profile"] == "uniforme"
    # Ensayo pequeño con el mismo preset: la curva incluye subida, pico y apagado.
    result=run_simulation({**options,"nodes":8})
    q=result["source_curve"]["rate_w_m3"]
    assert q[0] == q[-1] == 0
    assert max(q) == options["qmax_w_m3"]


def test_dirichlet_curves_use_calculated_case_and_saved_times():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para comprobar la lógica del gráfico")
    source = (ROOT/"web/app.js").read_text(encoding="utf-8")
    helpers = source[source.index("function historySeries("):source.index("function draw() {")]
    # Datos sintéticos: la condición pertenece al caso calculado, no al formulario.
    result = {"time_s":[0,10,20,23], "parameters":{"boundary_type":"dirichlet",
              "boundary_c":20,"bottom_type":"dirichlet","bottom_c":15},
              "history":{"center_c":[40,35,30,29],"max_c":[40,36,31,30],
                         "mean_c":[30,27,24,23]}}
    code = "const colors={center_c:'blue',max_c:'orange',mean_c:'purple'};"+helpers
    code += "const r="+json.dumps(result)+";const series=historySeries(r);"
    code += "console.log(JSON.stringify({series,frames:[0,.45,1].map(f=>historyFrameAt(r.time_s,f)),adiabatic:historySeries({...r,parameters:{boundary_type:'neumann',bottom_type:'robin'}}).length}));"
    output = subprocess.run([node,"-"],input=code,capture_output=True,text=True,check=True,timeout=10)
    actual = json.loads(output.stdout)
    assert actual["series"][0]["values"] == [40,35,30,29]
    assert actual["series"][3]["values"] == [20]*4
    assert actual["series"][4]["values"] == [15]*4
    assert actual["series"][3]["dashed"]
    assert actual["frames"] == [0,1,3]  # Incluye el último paso acortado.
    assert actual["adiabatic"] == 3  # No inventar una temperatura impuesta.


def test_height_profiles_include_dirichlet_faces_and_multiple_times():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node opcional para comprobar los perfiles")
    result=run_simulation({"mode":"3d","nodes":8,"length_x_m":2,
        "length_y_m":1,"length_z_m":0.75,"duration_days":0.1,
        "initial_c":20,"profile":"seno","amplitude_c":20,
        "boundary_type":"dirichlet","boundary_c":20,
        "bottom_type":"dirichlet","bottom_c":20})
    source=(ROOT/"web/app.js").read_text(encoding="utf-8")
    helpers=source[source.index("function historySeries("):source.index("function draw() {")]
    code=helpers+"const r="+json.dumps(result)+";console.log(JSON.stringify(heightProfiles(r,r.time_s.length-1)));"
    output=subprocess.run([node,"-"],input=code,capture_output=True,text=True,check=True,timeout=10)
    profiles=json.loads(output.stdout)
    assert profiles["heights"][0] == 0
    assert profiles["heights"][-1] == 0.75
    assert len(profiles["heights"]) == 10  # Ocho centros y dos caras físicas.
    assert len(profiles["series"]) == 5
    for curve in profiles["series"]:
        assert curve["values"][0] == curve["values"][-1] == 20
        f=curve["frame"]
        assert curve["values"][1:-1] == result["frames_c"][f][(4*8+4)*8:(4*8+4)*8+8]
    assert profiles["series"][0]["values"][4] > profiles["series"][-1]["values"][4]
