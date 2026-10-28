"""Referencias del ZIP adaptadas a Parameters: continuo, semidiscreto y estacionario.

La solución semidiscreta integra exactamente el tiempo del operador cartesiano
centrado y permite medir el orden temporal sin mezclar el error espacial (G05).
"""

import numpy as np


def sine_initial(p):
    """Producto de senos en los centros, con caras Dirichlet cero."""
    x = (np.arange(p.shape[0]) + 0.5) * p.spacing_m[0]
    y = (np.arange(p.shape[1]) + 0.5) * p.spacing_m[1]
    wave = np.sin(np.pi*x/p.lengths_m[0])[:, None] * np.sin(np.pi*y/p.lengths_m[1])[None, :]
    if len(p.shape) == 3:
        z = (np.arange(p.shape[2]) + 0.5) * p.spacing_m[2]
        wave = wave[:, :, None] * np.sin(np.pi*z/p.lengths_m[2])[None, None, :]
    return wave


def sine_exact(p, time_s, semidiscrete=False):
    """Seno continuo o autovalor espacial discreto; material homogéneo."""
    if not np.isscalar(p.alpha_m2_s):
        raise ValueError("La referencia sinusoidal exige material homogéneo")
    lengths, delta = np.asarray(p.lengths_m), p.spacing_m
    eigenvalue = np.sum((2*np.sin(np.pi*delta/(2*lengths))/delta)**2) if semidiscrete else np.sum((np.pi/lengths)**2)
    return sine_initial(p) * np.exp(-p.alpha_m2_s * eigenvalue * time_s)


def two_layer_steady(z_m, interface_m, length_m, k_below, k_above, bottom_c, top_c):
    """Perfil exacto estacionario por tramos, dos materiales en serie (G05)."""
    if not 0 < interface_m < length_m or min(k_below, k_above) <= 0:
        raise ValueError("Interfaz interior y conductividades positivas requeridas")
    flux = (top_c-bottom_c) / (interface_m/k_below + (length_m-interface_m)/k_above)
    z = np.asarray(z_m)
    return np.where(z < interface_m, bottom_c + flux*z/k_below,
                    bottom_c + flux*interface_m/k_below + flux*(z-interface_m)/k_above)
