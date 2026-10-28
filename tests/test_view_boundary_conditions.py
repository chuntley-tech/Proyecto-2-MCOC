"""Comprueba que el visor distingue caras impuestas y centros calculados."""

from dataclasses import replace
import json

import numpy as np
import pytest

from scripts.view_solutions import foundation_boundary_description, verification_solution
from thermal1d.solver import Dirichlet
from thermal3d import solve


@pytest.fixture(scope="module", params=[2, 3])
def case(request):
    return verification_solution(request.param)


def test_verification_faces_are_20_but_cell_centers_are_not_clamped(case):
    p, initial, final = case
    assert len(p.boundaries) == 2*len(p.shape)
    assert all(isinstance(b, Dirichlet) and b.temperature_c == 20 for b in p.boundaries.values())
    assert np.all(final > 20) and np.all(final < 40)
    assert final.max() < initial.max()
    # Solución exacta independiente, evaluada en los mismos centros físicos.
    exact = 20+(initial-20)*np.exp(-len(p.shape)*np.pi**2*p.alpha_m2_s*p.duration_s)
    # Medidos 1.156e-3 y 9.872e-4 °C: márgenes 2.60 y 2.53 veces.
    assert np.max(np.abs(final-exact)) < {2: 0.003, 3: 0.0025}[len(p.shape)]


def test_change_in_face_temperature_enters_half_cell_balance(case):
    p, initial, _ = case
    one = replace(p, duration_s=p.dt_s)
    warmer = replace(one, boundaries={**p.boundaries, "x-": Dirichlet(25)})
    difference = solve(warmer, initial).temperature_c[-1]-solve(one, initial).temperature_c[-1]
    expected = np.zeros(p.shape)
    expected[0] = 2*p.alpha_m2_s*p.dt_s/p.spacing_m[0]**2 * (25-20)
    # Restar temperaturas de hasta 40 °C acumula unos pocos ulps IEEE.
    np.testing.assert_allclose(difference, expected, rtol=0, atol=3*np.spacing(40.0))


def test_missing_boundary_metadata_is_not_invented(tmp_path):
    message = foundation_boundary_description(tmp_path/"field.npz", np.zeros((1,1,1)), 1.0, "new")
    assert "no incluidos" in message


def test_inconsistent_boundary_metadata_is_rejected(tmp_path):
    report = {"probe_index": [0,0,0], "voxel": {"ifc_input": {"sha256": "old"}}, "final_time_s": 1.0}
    (tmp_path/"demo_termica_fundacion.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="no coincide"):
        foundation_boundary_description(tmp_path/"field.npz", np.zeros((1,1,1)), 1.0, "new")
