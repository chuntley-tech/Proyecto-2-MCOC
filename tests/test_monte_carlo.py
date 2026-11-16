"""Semilla, trazabilidad y reglas de agregación del lote E12."""

from types import SimpleNamespace
import shutil
import subprocess

import pytest

from scripts import monte_carlo as mc


def test_sampler_is_repeatable_and_aggregation_requires_all_runs(tmp_path, monkeypatch):
    options = dict(count=2, seed=2026, snapshot=None, synthetic=True,
                   dt=600, hours=49, coarsen=2, distributions=mc.CONFIG / "monte_carlo_g8.json")
    lot = tmp_path / "a"
    mc.sample(SimpleNamespace(lot=lot, **options))
    mc.sample(SimpleNamespace(lot=tmp_path / "b", **options))
    manifest, fingerprint = mc.load_manifest(lot)
    assert (lot / "manifest.json").read_bytes() == (tmp_path / "b" / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="Faltan 2"):
        mc.aggregate(lot)

    calls = []

    def solve(args, config, construction, *, metrics_only):
        assert metrics_only and args.synthetic
        assert len({row["placement_c"] for row in construction["pours"]}) == 1
        sample = manifest["samples"][len(calls)]
        assert construction["pours"][0]["placement_c"] == sample["placement_c"]
        assert construction["hydration"]["theta_inf_c"] == sample["theta_inf_c"]
        assert construction["hydration"]["tau_h"] == sample["tau_h"]
        values = ((70.0, 21.0), (72.0, 18.0))[len(calls)]
        calls.append(sample)
        return dict(zip(mc.METRICS, values), energy_balance_relative=1e-15,
                    ifc_sha256=manifest["ifc_sha256"], weather_sha256=None)

    monkeypatch.setattr(mc.e12_case, "run", solve)
    mc.worker(lot, 0)
    mc.worker(lot, 0)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Faltan 1"):
        mc.aggregate(lot)
    mc.worker(lot, 1)
    result = mc.aggregate(lot)
    assert result["manifest_sha256"] == fingerprint
    assert result["tmax_c"]["percentiles_c"]["p50"] == 71.0
    assert result["tmax_c"]["exceedance_fraction"] == 0.5
    assert result["delta_t_max_c"]["exceedance_fraction"] == 0.5
    assert result["any_exceedance_fraction"] == 1.0

    row = mc.read_json(mc.result_path(lot, 1))
    row["manifest_sha256"] = "invalid"
    mc.write_json(mc.result_path(lot, 1), row)
    with pytest.raises(ValueError, match="incompatible"):
        mc.aggregate(lot)


def test_dashboard_keeps_monte_carlo_lots_separate_and_filters_runs():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node opcional para verificar el visor")
    app = (mc.ROOT / "web/app.js").read_text(encoding="utf-8")
    source = app[app.index("const mcMetrics"):app.index("const e11Planes")]
    setup = """
const assert=require('node:assert/strict');
function element(){return {children:[],classList:{toggle(){},add(){},remove(){}},value:'all',
  append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},setAttribute(){},addEventListener(){}};}
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
const document={createElement:element};
const num=(value,n)=>value.toFixed(n);
"""
    checks = """
const hash='a'.repeat(64);
const stat=(limit,count)=>({threshold_c:limit,mean_c:40,percentiles_c:{p05:20,p50:40,p95:70},exceedances:count});
const summary={manifest_sha256:hash,samples:2,any_exceedances:1,tmax_c:stat(70,1),delta_t_max_c:stat(20,0)};
const run=(id,temp)=>({manifest_sha256:hash,sample_id:id,parameters:{placement_c:20,theta_inf_c:45,tau_h:30},
  metrics:{tmax_c:temp,delta_t_max_c:20}});
mcLot=mergeMonteCarlo(mcLot,[{name:'run.json',data:run(1,71)}]);
mcLot=mergeMonteCarlo(mcLot,[{name:'aggregate.json',data:summary},{name:'run.json',data:run(0,70)}]);
drawMonteCarlo();
assert.equal($('mc-summary-rows').children.length,3);
assert.match($('mc-status').textContent,/2 simulaciones.*2 corridas/);
$('mc-filter').value='any';
drawMonteCarlo();
assert.equal($('mc-run-rows').children.length,1);
assert.equal($('mc-run-rows').children[0].children[0].textContent,'1');
assert.throws(()=>mergeMonteCarlo(mcLot,[{name:'otro.json',data:{...run(0,70),manifest_sha256:'b'.repeat(64)}}]),/otro lote/);
assert.throws(()=>mergeMonteCarlo(mcLot,[{name:'fuera.json',data:run(2,70)}]),/fuera/);
"""
    subprocess.run([node, "-"], input=setup + source + checks, text=True, encoding="utf-8",
                   check=True, timeout=20)
