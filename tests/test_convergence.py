from pathlib import Path

import pytest

from scripts.convergence import run

CONFIG = Path(__file__).resolve().parents[1] / "config" / "case_g8.json"


def test_observed_orders_match_the_scheme(tmp_path):
    summary = run(CONFIG, tmp_path)
    assert summary["spatial"]["slope"] == pytest.approx(2.0, abs=0.05)   # diferencias centrales
    assert summary["temporal"]["slope"] == pytest.approx(1.0, abs=0.05)  # Euler explícito
    for name in ("espacial.csv", "temporal.csv", "espacial.png", "temporal.png", "resumen.json"):
        assert (tmp_path / name).exists()
