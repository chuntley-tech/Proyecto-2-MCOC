"""Contraste del núcleo portátil JavaScript con el solver Python original.

Node se utiliza únicamente en estas pruebas de desarrollo, si está disponible;
el HTML entregado necesita solo un navegador, sin Node ni Python.
"""

from html.parser import HTMLParser
import base64
import gzip
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


@pytest.mark.parametrize("staged", [False, True])
def test_foundation_environment_matches_python_and_changes_temperature(pack, staged):
    base = {"mode": "fundacion", "resolution_m": 0.5, "duration_days": 0.4, "initial_c": 30}
    if staged:
        base.update(construction_mode="staged", pour_count=2,
                    pour_schedule=json.dumps([{"start_days": 0, "placement_c": 30},
                                              {"start_days": 0.25, "placement_c": 20}]))
    options = {**base, "environment_mode": "e10", "environment_wind": "synthetic",
               "environment_solar": "synthetic", "environment_formwork": "scheduled",
               "environment_strip_h": 4, "environment_insulation": "blanket",
               "environment_soil": "equivalent"}
    reference = run_simulation(options)
    portable = javascript(options, pack)
    np.testing.assert_allclose(portable["time_s"], reference["time_s"], rtol=1e-14)
    # Los dos exportadores redondean los campos guardados a cinco decimales.
    np.testing.assert_allclose(np.asarray(portable["frames_c"], dtype=float),
                               np.asarray(reference["frames_c"], dtype=float), atol=1.01e-5, rtol=0)
    assert portable["stats"]["balance_relative_error"] < 1e-12
    assert reference["stats"]["balance_relative_error"] < 1e-12
    assert portable["stats"]["dt_s"] <= pack["meta"]["environment"]["max_step_s"]
    assert "E10" in portable["boundary_used"]["laterales_y_expuestas"]
    assert "Suelo equivalente" in reference["boundary_used"]["base"]
    manual = run_simulation(base)
    assert np.nanmax(np.abs(np.asarray(reference["frames_c"][-1], dtype=float)
                            - np.asarray(manual["frames_c"][-1], dtype=float))) > 0.1
    if not staged:
        shade = run_simulation({**options, "environment_solar": "off"})
        assert reference["history"]["mean_c"][-1] > shade["history"]["mean_c"][-1]


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


def test_s8_ranking_uses_common_mesh_and_excludes_known_failures():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node no está disponible")
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    exceeds = re.search(r"^const s8Exceeds=.*$", app, re.MULTILINE)[0]
    rank = app[app.index("function rankS8Pours("):app.index("function drawS8Chart(")]
    subprocess.run([node, "-e", exceeds + "\n" + rank + """
const assert=require('node:assert/strict');
const mesh=(n,d,open=false)=>({mesh:n,delta:{value_c:d},tmax:{value_c:60},horizon_open:open});
const plan=(id,duration_h,...meshes)=>({plan:{id,duration_h},meshes});
const a=plan('A',12,mesh(24,16),mesh(48,15),mesh(96,19));
const b=plan('B',12,mesh(24,16),mesh(48,16));
const fast=plan('C',10,mesh(24,17),mesh(48,18),mesh(96,21));
const open=plan('D',9,mesh(24,17),mesh(48,18,true));
const data={mesh_levels:[24,48,96],plans:[b,fast,open,a]};
assert.equal(rankS8Pours(data).best,a);
assert.equal(rankS8Pours(data).common,48);
b.meshes.push(mesh(96,18));
open.meshes.push(mesh(96,18));
assert.equal(rankS8Pours(data).best,b);
assert.equal(rankS8Pours(data).common,96);
"""], check=True)


def test_s8_charts_plot_meshes_and_course_limits():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node no está disponible")
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    charts = app[app.index("function drawS8Chart("):app.index("function drawS8PoursTable(")]
    subprocess.run([node, "-e", charts + """
const assert=require('node:assert/strict');
const element=()=>({children:[],style:{},setAttribute(){},append(...nodes){this.children.push(...nodes)}});
const document={createElement:element,createTextNode:text=>text};
const output={replaceChildren(...nodes){this.charts=nodes}};
const $=()=>output;
const num=(value,digits)=>value.toFixed(digits);
const s8MeshNames=['Gruesa','Intermedia','Fina'];
const mesh=(mesh,delta,tmax)=>({mesh,delta:{value_c:delta},tmax:{value_c:tmax}});
const a={plan:{id:'S8-V01',duration_h:12.11},meshes:[mesh(24,16,57),mesh(48,17,58),mesh(96,19,59)]};
const b={plan:{id:'S8-V02',duration_h:25},meshes:[mesh(24,24,61)]};
const s8Pours={mesh_levels:[24,48,96],plans:[a,b],best:a};
drawS8PoursCharts([a,b]);
assert.equal(output.charts.length,3);
const [[durationA],[deltaA,deltaB],[tmaxA]]=output.charts.map(chart=>
  chart.children[2].children.map(row=>row.children[1].children));
const barValue=bar=>bar.children[1].children[1];
assert.deepEqual(durationA.map(barValue),['12.11']);
assert.deepEqual(deltaA.map(barValue),['16.00','17.00','19.00']);
assert.deepEqual(deltaB.map(barValue),['24.00','—','—']);
assert.match(deltaB[0].children[1].className,/s8-over/);
assert.equal(deltaA[0].children[0].children[1].style.left,'80%');
assert.deepEqual(tmaxA.map(barValue),['57.00','58.00','59.00']);
assert.equal(tmaxA[0].children[0].children[1].style.left,'87.5%');
drawS8PoursCharts([a]);
assert.ok(output.charts.every(chart=>chart.children[2].children.length===1));
"""], check=True)


def test_s8_spatial_charts_use_selected_plan_mesh_results():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node no está disponible")
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    spatial = app[app.index("function drawS8SpatialConvergence("):app.index("function drawS8PourDetail(")]
    subprocess.run([node, "-e", spatial + """
const assert=require('node:assert/strict');
const s8Pours={mesh_levels:[24,48,96]};
const elements={}, plots={};
const $=id=>elements[id]??=( {clientWidth:300} );
const num=(v,n)=>v.toFixed(n);
const lineChart=(id,[series],indices,options)=>{plots[id]={values:series.values,indices,options}};
const mesh=(mesh,tmax,delta)=>({mesh,dt:600,tmax:{value_c:tmax},delta:{value_c:delta}});
drawS8SpatialConvergence({meshes:[mesh(96,57.48,16.65),mesh(24,57.29,15.89),mesh(48,57.45,15.47)],
  apparent_convergence:{delta:{last_change_c:1.18,order:null,stable_sequence:false,target_c:.2}}});
assert.deepEqual(plots['s8-spatial-tmax'].values,[57.29,57.45,57.48]);
assert.deepEqual(plots['s8-spatial-delta'].values,[15.89,15.47,16.65]);
assert.deepEqual(plots['s8-spatial-delta'].options.xTickLabels,['n=24','n=48','n=96']);
assert.match(elements['s8-spatial-method'].textContent,/600 s/);
assert.match(elements['s8-spatial-delta-result'].textContent,/Orden aparente indeterminado/);
drawS8SpatialConvergence({meshes:[mesh(48,70,20)],apparent_convergence:{}});
assert.deepEqual(plots['s8-spatial-delta'].values,[undefined,20,undefined]);
assert.match(elements['s8-spatial-delta-result'].textContent,/tres mallas/);
"""], check=True)


def test_export_is_one_file_with_embedded_resources(tmp_path):
    output=build(tmp_path/"visor.html")
    text=output.read_text(encoding="utf-8")
    assert '<script src=' not in text and '<link rel="stylesheet"' not in text
    assert 'id="mcoc-pack"' in text and 'id="mcoc-worker"' in text
    assert "connect-src 'none'" in text
    assert 'value="1300" readonly' in text
    assert 'source-example' not in text and 'source-activate' not in text
    assert 'id="tab-project"' in text and 'id="panel-project"' in text
    assert 'id="tab-terrain"' in text and 'id="terrain-beacon"' in text
    assert 'id="tab-monte-carlo"' in text and 'id="mc-files"' in text
    from scripts.dashboard_jobs import EXAMPLES
    for name, path in EXAMPLES.items():
        example = re.search(rf'<script id="mcoc-example-{name}" type="text/plain">([A-Za-z0-9+/=]+)</script>', text)
        assert example is not None
        assert gzip.decompress(base64.b64decode(example.group(1))) == path.read_bytes()
    assert 'id="tab-plans"' in text
    assert '<dialog' not in text and '<h2 id="arcade-title">' in text
    from scripts.dashboard_jobs import POUR_COMPARISON
    for retired_id in ("plans-convergence", "plans-alternative", "s8-aligned-results", "s8-mc-results", "plans-mc-results"):
        assert f'id="{retired_id}"' not in text
    assert 'id="s8-pours-charts"' in text
    assert 'id="s8-spatial-tmax"' in text and 'id="s8-spatial-delta"' in text
    comparison = POUR_COMPARISON / "summary.json"
    if comparison.is_file():
        example = re.search(r'<script id="mcoc-example-plans" type="text/plain">([A-Za-z0-9+/=]+)</script>', text)
        assert example is not None
        bundle = json.loads(gzip.decompress(base64.b64decode(example.group(1))))
        assert set(bundle) == {"s8_pours"}
        s8_pours = bundle["s8_pours"]
        assert s8_pours["expected"] == 30
        assert s8_pours["completed"] == sum(len(item["meshes"]) for item in s8_pours["plans"])
        assert {item["plan"]["id"] for item in s8_pours["plans"]} == {f"S8-V{i:02d}" for i in range(1, 11)}
        assert s8_pours["mesh_levels"] == [24, 48, 96]
        assert s8_pours["member"] == "23"
        assert 'id="s8-pours"' in text
    embedded_relief = re.search(r'<script id="mcoc-terrain" type="application/json">(.*?)</script>', text, re.S)
    assert embedded_relief is not None
    terrain = json.loads(embedded_relief.group(1))
    assert terrain == json.loads((ROOT/"web/terrain_g8.json").read_text(encoding="utf-8"))
    site = json.loads((ROOT/"config/case_g8.json").read_text(encoding="utf-8"))["site"]
    assert (terrain["latitude"], terrain["longitude"]) == (site["latitude"], site["longitude"])
    assert len(terrain["elevation_m"]) == terrain["samples"]**2 and np.ptp(terrain["elevation_m"]) > 0
    texture = re.search(r'<script id="mcoc-texture" type="text/plain">([A-Za-z0-9+/=]+)</script>', text)
    assert texture is not None
    assert base64.b64decode(texture.group(1)) == (ROOT/"web/terrain_g8.jpg").read_bytes()
    assert 'Contains modified Copernicus Sentinel data 2016' in text
    assert 'id="foundation_geometry"' in text and 'id="pour_count"' in text
    assert "font-src 'none'" in text and "system-ui" in text
    assert "@font-face" not in text and "data:font/" not in text
    assert output.stat().st_size < 5_100_000  # Incluye la campaña ampliada y sus figuras.


def test_arcade_sequence_and_gameplay():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para comprobar la activación y el juego")
    source = (ROOT / "web/app.js").read_text(encoding="utf-8")
    arcade = source[source.index("(() => {\n  const sequence ="):]
    checks = """
const assert = require('node:assert/strict');
const callbacks = {}, timers = [], classes = new Set(), children = [];
let clock = 0, cleared = false, playerFocused = false;
const window = {matchMedia: () => ({matches: false}), addEventListener(name, cb) {callbacks[name] = cb;}};
const performance = {now: () => clock};
const setTimeout = cb => timers.push(cb);
const requestAnimationFrame = cb => cb;
const cancelAnimationFrame = () => {cleared = true;};
const focusOrigin = {isConnected: true, focus() {playerFocused = true;}};
function element() {
  return {
    events: {},
    focus() {},
    showModal() {this.open = true;},
    close() {this.open = false; this.events.close();},
    remove() {children.splice(children.indexOf(this), 1);},
    setAttribute() {},
    addEventListener(name, cb) {this.events[name] = cb;},
    getContext: () => null,
    querySelector(selector) {
      this.nodes ??= {};
      return this.nodes[selector] ??= element();
    },
  };
}
const document = {
  addEventListener(name, cb) {callbacks[name] = cb;},
  documentElement: {classList: {add: value => classes.add(value), remove: value => classes.delete(value)}},
  activeElement: focusOrigin,
  body: {append: node => children.push(node)},
  createElement: element,
};
function press(key, props = {}) {
  clock += 100;
  const event = {key, preventDefault() {this.prevented = true;}, stopPropagation() {}, ...props};
  callbacks.keydown(event);
  return event;
}
const code = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft','ArrowRight',
              'ArrowLeft', 'ArrowRight', 'B', 'a', 'Enter'];
"""
    exposed = arcade.removesuffix("})();\n") + (
        "return {maze, moves, playerHome, stepFrom, newGame, tick, interpolated, releaseDelays, stepMs};})();"
    )
    expectations = """
const engine = """ + exposed + """
assert.equal(children.length, 0);
code.slice(0,-1).forEach(key => press(key));
assert.equal(timers.length, 0);
press('Enter', {target: {closest: () => true}});
assert.equal(timers.length, 0);
press('ArrowUp');
clock += 4000;
code.slice(1).forEach(key => press(key));
assert.equal(timers.length, 0);
press('ArrowUp', {repeat: true});
code.slice(1).forEach(key => press(key));
assert.equal(timers.length, 0);
press('ArrowUp'); press('x');
code.slice(1).forEach(key => press(key));
assert.equal(timers.length, 0);
code.slice(0,-1).forEach(key => assert(!press(key).prevented));
assert(press('Enter').prevented);
assert(classes.has('visor-transition'));
assert.equal(children.length, 0);
timers.shift()();
assert.equal(classes.size, 0);
assert.equal(children.length, 1);
assert(children[0].open);
children[0].events.keydown({key: 'Escape', preventDefault() {}});
assert.equal(children.length, 0);
assert(cleared && playerFocused);
code.forEach(key => press(key));
assert.equal(timers.length, 1);

const {maze, moves, playerHome, stepFrom, newGame, tick, interpolated, releaseDelays, stepMs} = engine;
assert(maze.every(row => row.length === maze[0].length));
assert.deepEqual(stepFrom([0,8], moves.ArrowLeft), [28,8]);
assert.equal(stepFrom([14,5], moves.ArrowDown), null);
assert.deepEqual(interpolated([0,8],[28,8],.5),[-.5,8]);
assert.deepEqual(interpolated([10,11],[9,11],.5),[9.5,11]);
const reachable = new Set(), todo = [playerHome];
while (todo.length) {
  const pos = todo.pop();
  if (reachable.has(String(pos))) continue;
  reachable.add(String(pos));
  todo.push(...Object.values(moves).map(move => stepFrom(pos,move)).filter(Boolean));
}
const game = newGame();
for (const key of game.pellets.keys()) {
  assert(reachable.has(String([key%maze[0].length, Math.floor(key/maze[0].length)])));
}
game.phase = 'playing';
game.wanted = moves.ArrowLeft;
tick(game);
assert.deepEqual(game.player,[9,11]);
assert.equal(game.score,10);
assert(Object.values(moves).filter(move => stepFrom(playerHome, move)).length >= 3);
assert.deepEqual(releaseDelays.map(ticks => ticks*stepMs),[4050,6000,8100,10050]);
const release = newGame(), exits = [];
release.phase = 'playing';
release.player = [14,8]; // Aísla las salidas de la persecución durante el ensayo.
for (let i=0; i<100; i++) {
  tick(release);
  for (const ghost of release.ghosts) {
    if (release.ticks < ghost.releaseAt) assert.deepEqual(ghost.position,ghost.home);
    if (ghost.outside && exits[ghost.index] === undefined) exits[ghost.index] = release.ticks;
  }
}
assert.deepEqual(exits.map(ticks => ticks*stepMs),[4950,6900,9600,11550]);
game.player = [2,1]; game.wanted = moves.ArrowLeft;
Object.assign(game.ghosts[0],{position:[1,1],outside:true});
tick(game);
assert.equal(game.score,260);
assert(Math.abs(game.power*stepMs-6500) <= stepMs/2);
assert.equal(game.lives,3);
game.power = 0;
Object.assign(game.ghosts[1],{position:game.player,outside:true});
tick(game);
assert.equal(game.lives,2);
assert.equal(game.phase,'ready');
game.ghosts = [];
game.player = playerHome;
game.wanted = moves.ArrowLeft;
game.pellets = new Map([[11*maze[0].length+9,'.']]);
game.phase = 'playing';
tick(game);
assert.equal(game.phase,'won');
"""
    subprocess.run([node, "-"], input=checks + expectations, text=True, encoding="utf-8",
                   cwd=ROOT, check=True, timeout=20)


def test_terrain_detail_uses_ifc_and_cows_at_map_scale(pack):
    models = pack["meta"]["terrain_foundation"]
    vertices = np.concatenate([model["vertices_m"] for model in models])
    assert len(models) == pack["meta"]["ifc"]["components"]
    np.testing.assert_allclose(np.ptp(vertices, axis=0), pack["meta"]["ifc"]["lengths_m"], atol=1e-6)
    np.testing.assert_allclose(vertices.min(axis=0) + vertices.max(axis=0),
                               [0, 0, pack["meta"]["ifc"]["lengths_m"][2]], atol=1e-6)

    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para comprobar el zoom y la geometría del terreno")
    source = (ROOT / "web/terrain.js").read_text(encoding="utf-8")
    check = """
const assert = require('node:assert/strict');
const cow = terrainCow(12, -8, 2, 0.5);
const heights = cow.flatMap(face => face.points.map(p => p[2]));
assert.equal(Math.min(...heights), 2);
assert.equal(Math.max(...heights), 3.5);
const canvas = {getBoundingClientRect: () => ({width:800, height:450})};
const view = Object.assign(Object.create(TerrainView.prototype), {canvas, extent:18000, zoom:1, scheduleDraw() {}});
view.zoomBy(10000);
assert.equal(view.zoom, view.detailZoom());
assert.equal(view.zoom * 360 / view.extent, 12);
let fills = 0;
const context = {setTransform(){}, clearRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, closePath(){}, stroke(){}, fill(){ fills++; }};
const beacon = {style:{}, classList:{toggle(){}}};
Object.assign(view, {objectCanvas:{}, objectContext:context, beacon, objects:cow, foundationHeight:3.3});
const project = (x,y,z) => [400 + x*12, 252 + (y-z)*12, y+z];
view.drawObjects(project, false, 800, 450, 1);
assert.equal(fills, 0);
assert.equal(beacon.style.top, '252px');
view.drawObjects(project, true, 800, 450, 1);
assert.equal(fills, cow.length);
assert.equal(beacon.style.top, '212.4px');
"""
    subprocess.run([node, "-"], input=source + check, text=True, encoding="utf-8",
                   cwd=ROOT, check=True, timeout=20)


def test_portable_rejects_unstable_step(pack):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node opcional no instalado")
    code="const {runOffline}=require('./web/solver_worker.js');const p=JSON.parse(require('fs').readFileSync(0,'utf8'));try{runOffline({mode:'3d',dt_s:1000000000},p);process.exit(2);}catch(e){console.log(e.message);}"
    result=subprocess.run([node,"-e",code],input=json.dumps(pack),text=True,encoding="utf-8",cwd=ROOT,capture_output=True,timeout=30)
    assert result.returncode == 0 and "Estabilidad" in result.stdout
