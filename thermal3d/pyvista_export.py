"""Mallas exteriores E11 mediante PyVista, con índices para colorear cada instante."""

import numpy as np


def export_surfaces(material, spacing, origin):
    """Exporta caras del hormigón y suelo con el índice de su celda activa."""
    import pyvista as pv

    grid = pv.ImageData(dimensions=tuple(n + 1 for n in material.shape),
                        spacing=spacing, origin=origin)
    ids = np.full(material.shape, -1, dtype=np.int32)
    ids[material > 0] = np.arange(np.count_nonzero(material))
    grid.cell_data["frame_index"] = ids.ravel(order="F")
    vtk_material = material.ravel(order="F")
    surfaces = []
    for kind in (1, 2):
        cells = np.flatnonzero(vtk_material == kind)
        if not len(cells):
            continue
        surface = grid.extract_cells(cells).extract_surface(
            algorithm="geometry", pass_pointid=False, pass_cellid=False).triangulate()
        triangles = surface.faces.reshape(-1, 4)[:, 1:]
        surfaces.append({"material": kind, "points_m": np.round(surface.points, 5).tolist(),
                         "triangles": triangles.tolist(),
                         "frame_indices": surface.cell_data["frame_index"].tolist()})
    return {"engine": "PyVista " + pv.__version__, "surfaces": surfaces}
