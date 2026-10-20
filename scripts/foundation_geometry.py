"""Reconstrucción geométrica a partir de planta y sección aportadas por el usuario."""

import math
import numpy as np


def geometry_parts(g):
    """Tres sólidos: zócalo octagonal, transición aproximada y cilindro.

    La planta y sección fijan cotas. La superficie lateral de transición se
    asume como una interpolación radial y se aproxima mediante triángulos.
    """
    keys = ("length_m", "width_m", "height_m", "octagon_axis_half_m",
            "octagon_corner_coordinate_m", "base_height_m", "transition_height_m",
            "cylinder_height_m", "cylinder_diameter_m")
    if any(not math.isfinite(g[k]) or g[k] <= 0 for k in keys):
        raise ValueError("Las cotas geométricas deben ser finitas y positivas")
    a, c = g["octagon_axis_half_m"], g["octagon_corner_coordinate_m"]
    radius = g["cylinder_diameter_m"] / 2
    if not 0 < c < a or radius >= a:
        raise ValueError("Octágono o diámetro superior incompatibles")
    if not (math.isclose(2 * a, g["length_m"]) and math.isclose(2 * a, g["width_m"])):
        raise ValueError("La planta debe coincidir con las dimensiones exteriores")
    heights = [g[k] for k in ("base_height_m", "transition_height_m", "cylinder_height_m")]
    if not math.isclose(sum(heights), g["height_m"]):
        raise ValueError("Las tres alturas deben sumar la altura total")
    segments = g["transition_edge_segments"]
    if isinstance(segments, bool) or not isinstance(segments, int) or segments < 2:
        raise ValueError("transition_edge_segments debe ser un entero >= 2")
    polygon = np.array([(a, c), (c, a), (-c, a), (-a, c),
                        (-a, -c), (-c, -a), (c, -a), (a, -c)], dtype=float)
    weights = np.arange(segments) / segments
    bottom = np.concatenate([p + weights[:, None] * (q - p)
                             for p, q in zip(polygon, np.roll(polygon, -1, axis=0))])
    top = radius * bottom / np.linalg.norm(bottom, axis=1)[:, None]
    n = len(bottom)
    vertices = np.vstack([np.column_stack([bottom, np.zeros(n)]),
                          np.column_stack([top, np.full(n, heights[1])])])
    faces = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.extend([(i, j, n + j), (i, n + j, n + i)])
    return [
        dict(tag="G8-BASE-01", name="Zócalo octagonal", kind="polygon",
             polygon=polygon, z=0., height=heights[0]),
        dict(tag="G8-BASE-02", name="Transición inclinada", kind="mesh",
             vertices=vertices, faces=faces, z=heights[0], height=heights[1]),
        dict(tag="G8-BASE-03", name="Cilindro superior Ø7 m", kind="circle",
             radius=radius, z=heights[0] + heights[1], height=heights[2])
    ]
