"""Semilla, trazabilidad y reglas de agregación del lote E12."""

from types import SimpleNamespace

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
