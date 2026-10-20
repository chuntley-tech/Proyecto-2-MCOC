import json
from pathlib import Path

import numpy as np
import pytest

from scripts.run_case import main, run
from thermal1d.case import apply_override, load_case
from thermal1d.reference import sine_reference
from thermal1d.solver import Neumann, Robin, solve

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "case_g8.json"


def test_published_g8_case_is_reproducible():
    case = load_case(CONFIG)
    assert case.config["site"]["latitude"] == -41.222539
    assert case.config["site"]["longitude"] == -73.295603
    # Mantener el dominio térmico consistente con la fundación de 3,30 m.
    assert case.params.length_m == case.config["geometry"]["height_m"]
    result = solve(case.params, case.initial_c)
    exact = sine_reference(case.params, case.x_m, case.params.duration_s, 20.)
    assert result.time_s[-1] == 14 * 86400
    assert np.max(np.abs(result.temperature_c[-1] - exact)) < .005


def test_committed_results_match_a_fresh_run(tmp_path):
    summary = run(CONFIG, tmp_path)
    committed = json.loads((ROOT / "results" / "example_1d" / "summary.json").read_text(encoding="utf-8"))
    for key in ("final_max_abs_error_c", "final_rmse_c", "final_center_temperature_c", "fourier"):
        assert summary[key] == pytest.approx(committed[key], rel=1e-9)
    for name in ("profiles.csv", "history.csv", "profiles.png", "history.png", "summary.json"):
        assert (tmp_path / name).exists()


def test_overrides_change_only_the_requested_value():
    case = load_case(ROOT / "config" / "ejemplos" / "plantilla_hormigon.json",
                     ["top.h_w_m2k=20", "bottom.type=neumann", "thermal.duration_s=86400"])
    assert isinstance(case.params.top, Robin) and case.params.top.h_w_m2k == 20.
    assert isinstance(case.params.bottom, Neumann)
    assert case.params.duration_s == 86400.
    original = json.loads((ROOT / "config" / "ejemplos" / "plantilla_hormigon.json").read_text(encoding="utf-8"))
    assert original["top"]["h_w_m2k"] == 10.0


def test_override_requires_path_and_value():
    with pytest.raises(ValueError):
        apply_override({}, "top.h_w_m2k")


@pytest.mark.parametrize("bad", [
    {"bottom": {"type": "convection", "h_w_m2k": 1, "ambient_c": 20}},
    {"initial": {"type": "parabola"}},
    {"initial": {"type": "profile", "z_m": [0, 0], "temperature_c": [1, 2]}},
])
def test_invalid_case_definitions_are_rejected(bad):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config.update(bad)
    from thermal1d.case import case_from_config
    with pytest.raises(ValueError):
        case_from_config(config)


def test_unstable_time_step_is_rejected_by_default():
    with pytest.raises(ValueError, match="Paso inestable"):
        load_case(CONFIG, ["thermal.dt_s=1300"])


def test_allow_unstable_demo_runs_and_is_flagged(tmp_path):
    summary = main(["--config", str(ROOT / "config" / "ejemplos" / "01_dirichlet_video.json"),
                    "--output", str(tmp_path), "--set", "thermal.dt_s=0.55",
                    "--set", "thermal.duration_s=20", "--allow-unstable"])
    assert summary["unstable_step"] is True
    assert summary["max_temperature_c"] > 20.     # sobrepasa todo valor inicial: no es físico
