"""Contraste del núcleo portátil JavaScript con el solver Python original.

Node se utiliza únicamente en estas pruebas de desarrollo, si está disponible;
el HTML entregado necesita solo un navegador, sin Node ni Python.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from scripts.build_dashboard import build, build_pack
from thermal3d.dashboard import ROOT, run_simulation


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
    assert output.stat().st_size < 5_000_000


def test_portable_rejects_unstable_step(pack):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node opcional no instalado")
    code="const {runOffline}=require('./web/solver_worker.js');const p=JSON.parse(require('fs').readFileSync(0,'utf8'));try{runOffline({mode:'3d',dt_s:1000000000},p);process.exit(2);}catch(e){console.log(e.message);}"
    result=subprocess.run([node,"-e",code],input=json.dumps(pack),text=True,encoding="utf-8",cwd=ROOT,capture_output=True,timeout=30)
    assert result.returncode == 0 and "Estabilidad" in result.stdout
