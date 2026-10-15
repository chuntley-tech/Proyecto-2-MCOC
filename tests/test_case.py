import json
from pathlib import Path

import numpy as np

from thermal1d.solver import Parameters, sine_reference, solve


def test_published_g8_case_is_reproducible():
    config = json.loads((Path(__file__).resolve().parents[1] / "config/case_g8.json").read_text(encoding="utf-8"))
    assert config["site"]["latitude"] == -41.222539
    assert config["site"]["longitude"] == -73.295603
    p = Parameters(**config["thermal"])
    assert p.length_m == config["geometry"]["height_m"]
    x = np.linspace(0, p.length_m, p.nodes)
    amplitude = config["verification"]["amplitude_c"]
    result = solve(p, sine_reference(p, x, 0, amplitude))
    exact = sine_reference(p, x, p.duration_s, amplitude)
    assert result.time_s[-1] == 14 * 86400
    assert np.max(np.abs(result.temperature_c[-1] - exact)) < .005
