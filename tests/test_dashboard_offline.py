"""Contraste del núcleo portátil JavaScript con el solver Python original.

Node se utiliza únicamente en estas pruebas de desarrollo, si está disponible;
el HTML entregado necesita solo un navegador, sin Node ni Python.
"""

from html.parser import HTMLParser
import base64
import json
from pathlib import Path
import shutil
import subprocess
import re

import numpy as np
import pytest

from scripts.build_dashboard import build, build_pack
from thermal3d.dashboard import ROOT, run_simulation


@pytest.mark.parametrize("mode", ["1d", "2d", "3d"])
def test_cosine_heat_source_matches_python_and_start_of_step_integral(mode, pack):
    """Pulso sintético adiabático: cada celda sigue la integral discreta en t_n."""
    options={"mode":mode,"nodes":8,"duration_days":0.051,"initial_c":20,
             "source_type":"cosine","qmax_w_m3":1400,"source_duration_days":0.02,
             "boundary_type":"neumann","bottom_type":"neumann","dt_s":100}
    reference=run_simulation(options)
    portable=javascript(options,pack)
    from thermal3d.dashboard import source_value, validate_options
    o=validate_options(options)
    duration=o["duration_days"]*86400
    starts=np.arange(int(np.ceil(duration/100)))*100
    widths=np.minimum(100,duration-starts)
    expected=20+sum(source_value(o,float(t))*w for t,w in zip(starts,widths))/(o["density_kg_m3"]*o["specific_heat_j_kgk"])
    # Sin gradientes, Euler integra exactamente la suma izquierda, salvo redondeo Float64.
    np.testing.assert_allclose(reference["history"]["center_c"][-1],expected,rtol=1e-13,atol=0)
    np.testing.assert_allclose(portable["history"]["center_c"],reference["history"]["center_c"],rtol=0,atol=2e-11)
    np.testing.assert_allclose(portable["frames_c"][-1],np.round(expected,5),rtol=0,atol=1e-5)
    np.testing.assert_allclose(portable["source_curve"]["rate_w_m3"],reference["source_curve"]["rate_w_m3"],rtol=0,atol=1e-10)
    assert max(portable["source_curve"]["rate_w_m3"]) == 1400
    assert portable["source_curve"]["rate_w_m3"][-1] == 0
    if mode!='1d':
        assert portable["stats"]["balance_relative_error"] < 1e-12


@pytest.fixture(scope="module")
def pack():
    return build_pack(resolutions=(0.5,0.25))


def javascript(options, pack):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional no instalado: contraste JavaScript de desarrollo")
    code = "const {runOffline}=require('./web/solver_worker.js');const p=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(runOffline(p.options,p.pack)));"
    result = subprocess.run([node,"-e",code],input=json.dumps({"options":options,"pack":pack}),
                            text=True,encoding="utf-8",cwd=ROOT,capture_output=True,timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["1d", "2d", "3d", "fundacion"])
def test_portable_solver_matches_python(mode, pack):
    options = {"mode":mode,"nodes":12,"duration_days":0.1,"resolution_m":0.5,
               "initial_c":30,"profile":"seno","amplitude_c":5,
               "boundary_type":"robin","boundary_c":10,"h_w_m2k":12,
               "bottom_type":"neumann","source_w_m3":80}
    reference = run_simulation(options)
    portable = javascript(options, pack)
    assert portable["shape"] == reference["shape"]
    assert portable["stats"]["steps"] == reference["stats"]["steps"]
    np.testing.assert_allclose(portable["time_s"],reference["time_s"],rtol=2e-15,atol=1e-12)
    # Campos visuales redondeados a cinco decimales en ambas versiones.
    np.testing.assert_allclose(portable["frames_c"],reference["frames_c"],rtol=0,atol=1.01e-5)
    # Historia sin redondear: tolerancia de acumulación de sumas Float64, no error físico.
    for key in ("center_c","min_c","max_c","mean_c"):
        np.testing.assert_allclose(portable["history"][key],reference["history"][key],rtol=0,atol=2e-11)


@pytest.mark.parametrize("boundary", ["dirichlet","neumann","robin"])
def test_each_portable_boundary_matches_python(boundary, pack):
    options={"mode":"3d","nodes":8,"duration_days":0.02,"boundary_type":boundary,
             "bottom_type":boundary,"boundary_c":20,"bottom_c":20,
             "flux_in_w_m2":15,"bottom_flux_in_w_m2":-5,"source_w_m3":25}
    reference=run_simulation(options)
    portable=javascript(options,pack)
    np.testing.assert_allclose(portable["frames_c"],reference["frames_c"],rtol=0,atol=1.01e-5)


def test_nominal_foundation_seven_days_matches_python(pack):
    options={"resolution_m":0.25}
    reference=run_simulation(options)
    portable=javascript(options,pack)
    np.testing.assert_allclose(portable["history"]["center_c"],reference["history"]["center_c"],rtol=0,atol=2e-11)
    assert portable["stats"]["balance_relative_error"] < 1e-12
    assert portable["history"]["center_c"][-1] == pytest.approx(27.462812176219007,abs=2e-11)


@pytest.mark.parametrize("count",[1,4,5])
def test_scaled_foundation_and_pour_plan_match_python(count,pack):
    options={"mode":"fundacion","resolution_m":0.5,"duration_days":0.1,
        "foundation_geometry":"scaled","foundation_x_m":21.6,
        "foundation_y_m":14.4,"foundation_height_m":4.95,"pour_count":count,
        "source_type":"cosine","source_duration_days":0.05}
    reference=run_simulation(options)
    portable=javascript(options,pack)
    assert portable["active_indices"] == reference["active_indices"]
    assert portable["pour_plan"]["cell_pour_id"] == reference["pour_plan"]["cell_pour_id"]
    np.testing.assert_allclose(portable["positions_m"],reference["positions_m"],rtol=0,atol=5.1e-9)
    # Estadísticas Float64; campos exportados con cinco decimales.
    np.testing.assert_allclose(portable["frames_c"],reference["frames_c"],rtol=0,atol=1.01e-5)
    np.testing.assert_allclose(portable["history"]["mean_c"],reference["history"]["mean_c"],rtol=0,atol=2e-11)
    for actual,expected in zip(portable["pour_plan"]["layers"],reference["pour_plan"]["layers"]):
        assert actual["cells"] == expected["cells"]
        assert actual["voxel_volume_m3"] == pytest.approx(expected["voxel_volume_m3"],rel=1e-14)


@pytest.mark.parametrize("boundary", ["dirichlet", "neumann", "robin"])
def test_editable_block_dimensions_and_controls(boundary, pack):
    """Bloque sintético anisótropo: dimensiones, malla, fuente y bordes reales."""
    options = {"mode":"3d", "nodes":8, "length_x_m":2.5,
               "length_y_m":1.25, "length_z_m":0.75, "duration_days":0.01,
               "initial_c":25, "profile":"seno", "amplitude_c":7,
               "conductivity_w_mk":3, "density_kg_m3":2300,
               "specific_heat_j_kgk":950, "source_w_m3":100,
               "boundary_type":boundary, "boundary_c":20, "h_w_m2k":15,
               "resistance_m2k_w":0.1, "flux_in_w_m2":10,
               "bottom_type":"robin", "bottom_c":18, "bottom_h_w_m2k":8,
               "dt_s":60}
    reference = run_simulation(options)
    portable = javascript(options, pack)
    assert portable["lengths_m"] == [2.5,1.25,0.75]
    np.testing.assert_allclose(portable["spacing_m"], [2.5/8,1.25/8,0.75/8], rtol=0,atol=0)
    # Igual discretización Float64; campos exportados redondeados a cinco decimales.
    np.testing.assert_allclose(portable["frames_c"], reference["frames_c"],rtol=0,atol=1.01e-5)
    np.testing.assert_allclose(portable["history"]["center_c"],reference["history"]["center_c"],rtol=0,atol=2e-11)
    assert portable["stats"]["balance_relative_error"] < 1e-12
    larger = javascript({**options,"length_x_m":5}, pack)
    assert abs(larger["history"]["center_c"][-1]-portable["history"]["center_c"][-1]) > 1e-4


@pytest.mark.parametrize("boundary", ["dirichlet","neumann","robin"])
def test_portable_nodal_endpoints_match_python(boundary,pack):
    options={"mode":"1d","nodes":67,"duration_days":0.1,"profile":"seno","amplitude_c":20,
             "initial_c":20,"boundary_type":boundary,"bottom_type":boundary,"boundary_c":20,
             "bottom_c":20,"flux_in_w_m2":15,"bottom_flux_in_w_m2":-5}
    reference=run_simulation(options)
    portable=javascript(options,pack)
    np.testing.assert_allclose(portable["history"]["center_c"],reference["history"]["center_c"],rtol=0,atol=2e-11)
    np.testing.assert_allclose(portable["frames_c"],reference["frames_c"],rtol=0,atol=1.01e-5)


def test_export_is_one_file_with_embedded_resources(tmp_path):
    output=build(tmp_path/"visor.html")
    text=output.read_text(encoding="utf-8")
    assert '<script src=' not in text and '<link rel="stylesheet"' not in text
    assert 'id="mcoc-pack"' in text and 'id="mcoc-worker"' in text
    assert "connect-src 'none'" in text
    assert 'value="1300" readonly' in text
    assert 'source-example' not in text and 'source-activate' not in text
    assert 'id="tab-project"' in text and 'id="panel-project"' in text
    assert 'id="foundation_geometry"' in text and 'id="pour_count"' in text
    # La fuente de Google Fonts y su licencia viajan dentro del único HTML.
    embedded_font=re.search(r'data:font/ttf;base64,([A-Za-z0-9+/=]+)',text)
    assert embedded_font is not None
    assert base64.b64decode(embedded_font.group(1)) == (ROOT/"web/fonts/Inter-Variable.ttf").read_bytes()
    assert 'id="mcoc-font-license"' in text and 'SIL OPEN FONT LICENSE' in text
    assert "font-src data:" in text
    assert output.stat().st_size < 5_000_000


def test_portable_rejects_unstable_step(pack):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node opcional no instalado")
    code="const {runOffline}=require('./web/solver_worker.js');const p=JSON.parse(require('fs').readFileSync(0,'utf8'));try{runOffline({mode:'3d',dt_s:1000000000},p);process.exit(2);}catch(e){console.log(e.message);}"
    result=subprocess.run([node,"-e",code],input=json.dumps(pack),text=True,encoding="utf-8",cwd=ROOT,capture_output=True,timeout=30)
    assert result.returncode == 0 and "Estabilidad" in result.stdout
