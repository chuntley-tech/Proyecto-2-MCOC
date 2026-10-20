"""Soluciones exactas usadas para verificar el solver 1D.

Todas suponen propiedades constantes. Ninguna representa la fundación real:
sirven para comprobar que el código resuelve correctamente la ecuación.
"""

import math

import numpy as np

from .solver import Dirichlet, Neumann, Parameters, Robin


def _dirichlet_ends(p: Parameters):
    if not (isinstance(p.bottom, Dirichlet) and isinstance(p.top, Dirichlet)):
        raise ValueError("Esta referencia requiere bordes Dirichlet en ambos extremos")
    return p.bottom.temperature_c, p.top.temperature_c


def linear_dirichlet_profile(p: Parameters, x_m):
    """Perfil lineal entre las temperaturas Dirichlet de ambos extremos."""
    bottom_c, top_c = _dirichlet_ends(p)
    return bottom_c + (top_c - bottom_c) * np.asarray(x_m, dtype=float) / p.length_m


def sine_reference(p: Parameters, x_m, time_s, amplitude_c: float):
    """Solución exacta continua: perfil lineal estacionario + primer modo seno.

    T(z, t) = T_lineal(z) + A sen(πz/L) exp[−α (π/L)² t]
    """
    x = np.asarray(x_m, dtype=float)
    decay = np.exp(-p.alpha_m2_s * (math.pi / p.length_m)**2 * np.asarray(time_s, dtype=float))
    return linear_dirichlet_profile(p, x) + amplitude_c * np.sin(math.pi * x / p.length_m) * decay


def sine_reference_semidiscrete(p: Parameters, x_m, time_s, amplitude_c: float):
    """Misma condición inicial, integrando EXACTAMENTE en el tiempo el sistema
    ya discretizado en el espacio (mismo Δz que el solver).

    El modo seno es un modo propio de la segunda diferencia central, con
    valor propio λ_h = [2 sen(πΔz / 2L) / Δz]². La diferencia entre el solver
    y esta solución es solo error temporal: sirve para medir la convergencia
    en Δt sin que el error espacial la contamine.
    """
    x = np.asarray(x_m, dtype=float)
    lambda_h = (2 * math.sin(math.pi * p.dx_m / (2 * p.length_m)) / p.dx_m)**2
    decay = np.exp(-p.alpha_m2_s * lambda_h * np.asarray(time_s, dtype=float))
    return linear_dirichlet_profile(p, x) + amplitude_c * np.sin(math.pi * x / p.length_m) * decay


def slab_step_reference(p: Parameters, x_m, time_s: float, initial_c: float, terms: int = 400):
    """Losa a temperatura uniforme cuyas caras pasan bruscamente a T_b (serie de Fourier).

    T(z, t) = T_b + (T_0 − T_b) Σ_(n impar) 4/(nπ) sen(nπz/L) exp[−α (nπ/L)² t]
    Requiere la misma temperatura Dirichlet en ambos extremos y t > 0.
    """
    bottom_c, top_c = _dirichlet_ends(p)
    if bottom_c != top_c:
        raise ValueError("La serie requiere la misma temperatura en ambos extremos")
    if time_s <= 0:
        raise ValueError("La serie se evalúa para t > 0")
    x = np.asarray(x_m, dtype=float)
    series = np.zeros_like(x)
    for n in range(1, 2 * terms, 2):
        series += (4 / (n * math.pi) * np.sin(n * math.pi * x / p.length_m)
                   * math.exp(-p.alpha_m2_s * (n * math.pi / p.length_m)**2 * time_s))
    return bottom_c + (initial_c - bottom_c) * series


def linear_steady_state(p: Parameters, x_m):
    """Estado estacionario sin fuente: T(z) = a + G z, con los bordes de p.

    Admite Dirichlet, Robin con ambiente constante y Neumann (no ambos
    Neumann, porque entonces no hay un único estacionario). El flujo que va
    hacia +z es −kG: entra por abajo y sale por arriba.
    """
    if callable(p.source_w_m3) or p.source_w_m3 != 0:
        raise ValueError("El estacionario lineal requiere fuente nula")
    k, length = p.conductivity_w_mk, p.length_m
    rows, rhs = [], []
    for boundary, at_top in ((p.bottom, False), (p.top, True)):
        sign = 1.0 if at_top else -1.0          # flujo que entra = sign·k·G
        if isinstance(boundary, Dirichlet):
            rows.append([1.0, length if at_top else 0.0])
            rhs.append(boundary.temperature_c)
        elif isinstance(boundary, Neumann):
            rows.append([0.0, sign * k])
            rhs.append(boundary.flux_in_w_m2)
        elif isinstance(boundary, Robin):
            if callable(boundary.ambient_c):
                raise ValueError("El estacionario requiere temperatura ambiente constante")
            h = boundary.h_w_m2k
            # sign·k·G = h (T_amb − a − G z_borde)
            rows.append([h, sign * k + h * (length if at_top else 0.0)])
            rhs.append(h * boundary.ambient_c)
    a, gradient = np.linalg.solve(np.array(rows), np.array(rhs))
    return a + gradient * np.asarray(x_m, dtype=float)


def uniform_source_adiabatic(p: Parameters, initial_c: float, time_s):
    """Dominio adiabático con fuente uniforme: T = T_0 + q̇ t / (ρ cp)."""
    if callable(p.source_w_m3):
        raise ValueError("Requiere una fuente constante")
    return initial_c + p.source_w_m3 * np.asarray(time_s, dtype=float) / p.rho_cp


def source_steady_parabola(p: Parameters, x_m):
    """Estacionario con fuente uniforme y la misma temperatura Dirichlet en
    ambos extremos: T = T_b + q̇ z (L − z) / (2k)."""
    bottom_c, top_c = _dirichlet_ends(p)
    if bottom_c != top_c or callable(p.source_w_m3):
        raise ValueError("Requiere extremos iguales y fuente constante")
    x = np.asarray(x_m, dtype=float)
    return bottom_c + p.source_w_m3 * x * (p.length_m - x) / (2 * p.conductivity_w_mk)
