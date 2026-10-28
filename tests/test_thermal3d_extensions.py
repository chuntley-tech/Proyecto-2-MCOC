"""Regresión de las mejoras adaptadas del ZIP; parámetros sintéticos."""

from dataclasses import replace

import numpy as np
import pytest

from scripts.convergence_nd import study
from scripts.verify import main
from thermal1d.solver import Dirichlet
from thermal3d import Parameters, prepare, solve
from thermal3d.extra_verification import exposed, heterogeneous_energy, insulation, material_source, materials
from thermal3d.reference import sine_exact, sine_initial
from thermal3d.solver import effective_h


@pytest.fixture(scope="module")
def extra():
    return {"materials": materials(), "energy": heterogeneous_energy(), "source": material_source(),
            "exposed": exposed(), "temporal": study()["temporal"]}


def test_two_materials_and_harmonic_interface(extra):
    # Perfil lineal por tramos exactamente estacionario: error medido cero.
    assert extra["materials"]["max_steady_error_c"] == 0
    # Error medido 1.78e-15 W/K por representación binaria de Δ=0.05.
    assert abs(extra["materials"]["interface_conductance_w_k"]-extra["materials"]["expected_conductance_w_k"]) < 5e-15


def test_heterogeneous_energy_conserved(extra):
    # Error medido 5.116e-16; margen de 2.54 veces con capacidades variables.
    assert extra["energy"]["relative_energy_error"] < 1.3e-15


def test_source_uses_each_cell_capacity(extra):
    # Un paso: tolerancia de tres ulps relativos, no error de discretización.
    assert extra["source"]["max_relative_cell_error"] < 7e-16
    # Residuo medido 6.78e-21 J; margen 2.95 veces.
    assert extra["source"]["energy_balance_error_j"] < 2e-20


def test_exposed_faces_and_energy_ledger(extra):
    r = extra["exposed"]
    assert r["boundary_heat_in_j"] < 0
    assert r["source_heat_in_j"] > 0
    # Residuo medido 2.935e-16; margen 2.38 veces, por debajo de 1e-12.
    assert r["max_energy_balance_relative_error"] < 7e-16
    assert r["inactive_max_change_c"] == 0


@pytest.mark.parametrize("dim", ["2D", "3D"])
def test_temporal_order_against_semidiscrete(extra, dim):
    # Desviación máxima medida 0.00556: margen 2.7 sobre la desviación al orden 1.
    np.testing.assert_allclose(extra["temporal"][dim]["orders"], 1.0, atol=0.015, rtol=0)


def test_semidiscrete_reference_is_independent_euler_oracle():
    p = Parameters((7, 9), (0.7, 1.8), 1.0, 2.0, 3.0, 0.0003, 0.003,
                   {face: Dirichlet(0) for face in ("x-", "x+", "y-", "y+")})
    eigenvalue = np.sum((2*np.sin(np.pi*p.spacing_m/(2*np.asarray(p.lengths_m)))/p.spacing_m)**2)
    exact_euler = sine_initial(p)*(1-p.alpha_m2_s*p.dt_s*eigenvalue)**10
    result = solve(p, sine_initial(p), save_every=10**9)
    # Producto autovector: hasta cinco redondeos de doble precisión.
    np.testing.assert_allclose(result.temperature_c[-1], exact_euler, atol=1e-15, rtol=0)
    assert np.max(np.abs(result.temperature_c[-1]-sine_exact(p, p.duration_s, True))) > 0


def test_constant_fields_preserve_scalar_api():
    p = Parameters((3, 4, 5), (0.9, 1.6, 2.5), 2.0, 2.0, 3.0, 0.0001, 0.003)
    initial = np.random.default_rng(2026).uniform(10, 30, p.shape)
    fields = replace(p, conductivity_w_mk=np.full(p.shape, 2.0),
                     density_kg_m3=np.full(p.shape, 2.0), specific_heat_j_kgk=np.full(p.shape, 3.0))
    np.testing.assert_array_equal(solve(p, initial).temperature_c, solve(fields, initial).temperature_c)


def test_heterogeneous_local_stability_includes_capacity():
    p = Parameters((3, 4), (0.9, 1.2), np.ones((3, 4)), np.ones((3, 4)), 1.0, 1e-7, 0.001,
                   {"x-": Dirichlet(0)})
    p.density_kg_m3[0] = 0.1
    c = prepare(p)
    with pytest.raises(ValueError, match="Estabilidad"):
        prepare(replace(p, dt_s=min(c.general_dt_s, c.local_dt_s)*(1+1e-8)))


def test_insulation_series_resistance_and_zero_h():
    r = insulation()
    assert r["effective_h_w_m2k"] == r["expected_h_w_m2k"]
    assert r["zero_h_w_m2k"] == 0
    assert effective_h(10, 0.5) < effective_h(10)
    assert exposed(h_w_m2k=0, source_w_m3=0)["boundary_heat_in_j"] == 0


@pytest.mark.parametrize("values", [(float("nan"),), (-1,), (10, -1), (10, float("inf"))])
def test_invalid_insulation_rejected(values):
    with pytest.raises(ValueError):
        effective_h(*values)


def test_cli_selection_overrides_and_matrix(tmp_path):
    report = main(["--only", "exposed", "--set", "exposed.h_w_m2k=5", "--output", str(tmp_path)])
    assert report["exposed"]["h_w_m2k"] == 5
    assert report["matrix"][0]["passed"]
    assert (tmp_path/"matriz.csv").is_file() and (tmp_path/"matriz.md").is_file()
    with pytest.raises(ValueError, match="desconocido"):
        main(["--set", "exposed.inventado=1", "--output", str(tmp_path)])
