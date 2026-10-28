"""IFC guardado → triangulación IfcOpenShell → máscara cartesiana (G04/G08).

Clasificación por centro mediante paridad de rayos verticales sobre mallas
cerradas. No reconstruye geometría desde el JSON. Un componente geométrico
no equivale automáticamente a una vertida ni a un material diferente.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Mesh:
    """Triángulos en coordenadas globales SI y volumen de referencia del IFC."""

    guid: str
    name: str
    vertices: np.ndarray
    faces: np.ndarray
    volume_m3: float


@dataclass(frozen=True)
class VoxelGrid:
    """Grilla con origen global, centros locales y etiquetas de componente."""

    origin_m: np.ndarray
    lengths_m: np.ndarray
    spacing_m: np.ndarray
    component: np.ndarray
    report: dict

    @property
    def active(self):
        return self.component > 0


def load_ifc_meshes(path, guids=None):
    """Lee los sólidos reales del IFC; valida esquema, cierre y unidades SI."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.shape
    import ifcopenshell.validate

    path = Path(path).resolve()
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    model = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    if any(row["level"] == "error" for row in logger.statements):
        raise ValueError("IFC inválido: revise scripts.inspect_ifc")
    if guids is not None and (not guids or len(set(guids)) != len(guids)):
        raise ValueError("Los GUID deben ser únicos y no vacíos")
    try:
        elements = [model.by_guid(guid) for guid in guids] if guids is not None else model.by_type("IfcFooting")
    except RuntimeError as error:
        raise ValueError("Falta un GUID seleccionado en el IFC") from error
    if not elements:
        raise ValueError("No hay sólidos seleccionados en el IFC")
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    settings.set(settings.CONVERT_BACK_UNITS, False)
    meshes = []
    for element in elements:
        if not element.is_a("IfcFooting"):
            raise ValueError("Esta importación selecciona objetos IfcFooting")
        shape = ifcopenshell.geom.create_shape(settings, element)
        vertices = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
        faces = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)
        validate_mesh(vertices, faces)
        volume = float(ifcopenshell.util.shape.get_volume(shape.geometry))
        if not np.isfinite(volume) or volume <= 0:
            raise ValueError("Volumen IFC no positivo o no finito")
        meshes.append(Mesh(element.GlobalId, element.Name or element.GlobalId, vertices, faces, volume))
    if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
        raise ValueError("El IFC cambió durante la lectura; guarde y reintente")
    return meshes, {"file": path.name, "sha256": fingerprint, "geometry_source": "IFC guardado, triangulado con IfcOpenShell; coordenadas globales SI"}


def validate_mesh(vertices, faces):
    """Exige triángulos finitos, no degenerados, y dos caras por arista."""
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.all(np.isfinite(vertices)):
        raise ValueError("Vértices inválidos")
    if faces.ndim != 2 or faces.shape[1] != 3 or not faces.size or faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("Triángulos inválidos")
    tri = vertices[faces]
    if np.any(np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1) == 0):
        raise ValueError("Triángulos degenerados")
    edges = np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [2, 0]])), axis=1)
    if np.any(np.unique(edges, axis=0, return_counts=True)[1] != 2):
        raise ValueError("La malla debe ser cerrada y sin aristas no manifold")


def inside_mesh(x, y, z, mesh):
    """Paridad de cruces: bucle por triángulos, operaciones vectorizadas por puntos.

    Perturbación determinista <1e-9 del tamaño de caja para evitar aristas
    compartidas. No es un método de cut cells ni una certificación geométrica.
    """
    size = max(float(np.ptp(mesh.vertices, axis=0).max()), 1.0)
    x = x + size * 1e-10 * np.sqrt(2)
    y = y + size * 1e-10 * np.sqrt(3)
    counts = np.zeros((len(x), len(y), len(z)), dtype=np.int32)
    for tri in mesh.vertices[mesh.faces]:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = tri
        det = (y1-y2)*(x0-x2) + (x2-x1)*(y0-y2)
        if abs(det) <= np.finfo(float).eps * size**2:
            continue
        i0, i1 = np.searchsorted(x, [min(x0, x1, x2), max(x0, x1, x2)])
        j0, j1 = np.searchsorted(y, [min(y0, y1, y2), max(y0, y1, y2)])
        if i0 == i1 or j0 == j1:
            continue
        px, py = np.meshgrid(x[i0:i1], y[j0:j1], indexing="ij")
        a = ((y1-y2)*(px-x2) + (x2-x1)*(py-y2)) / det
        b = ((y2-y0)*(px-x2) + (x0-x2)*(py-y2)) / det
        hit = (a >= 0) & (b >= 0) & (a+b <= 1)
        height = a*z0 + b*z1 + (1-a-b)*z2
        counts[i0:i1, j0:j1] += hit[..., None] & (z[None, None, :] < height[..., None])
    return counts % 2 == 1


def voxelize(meshes, requested_spacing_m, source=None):
    """Ajusta Δ=L/ceil(L/Δ_solicitado), sin recortar el IFC ni usar cotas JSON."""
    if not meshes or len(meshes) > np.iinfo(np.int16).max:
        raise ValueError("Cantidad de componentes no admitida")
    requested = np.broadcast_to(np.asarray(requested_spacing_m, dtype=float), (3,))
    if not np.all(np.isfinite(requested)) or np.any(requested <= 0):
        raise ValueError("Resolución finita positiva requerida")
    low = np.min([m.vertices.min(axis=0) for m in meshes], axis=0)
    high = np.max([m.vertices.max(axis=0) for m in meshes], axis=0)
    lengths = high-low
    ratio = lengths/requested
    # Tolera ruido de exportación IFC de unas centésimas de micrómetro.
    shape = np.where(np.isclose(ratio, np.rint(ratio), rtol=1e-9, atol=1e-7),
                     np.rint(ratio), np.ceil(ratio)).astype(int)
    if np.any(shape < 1):
        raise ValueError("Dominio degenerado")
    delta = lengths/shape
    x = low[0] + (np.arange(shape[0])+0.5)*delta[0]
    y = low[1] + (np.arange(shape[1])+0.5)*delta[1]
    z = low[2] + (np.arange(shape[2])+0.5)*delta[2]
    component = np.zeros(tuple(shape), dtype=np.int16)
    records = []
    for number, mesh in enumerate(meshes, 1):
        inside = inside_mesh(x, y, z, mesh)
        if np.any(inside & (component > 0)):
            raise ValueError("Solapamiento entre sólidos en centros activos; no se asignará un componente arbitrario")
        component[inside] = number
        volume = float(inside.sum() * np.prod(delta))
        records.append({"component": number, "guid": mesh.guid, "name": mesh.name,
                        "ifc_volume_m3": mesh.volume_m3, "voxel_volume_m3": volume,
                        "relative_volume_error": abs(volume-mesh.volume_m3)/mesh.volume_m3})
    if not component.any():
        raise ValueError("La resolución no capturó ninguna celda activa")
    exact = sum(m.volume_m3 for m in meshes)
    volume = float(np.count_nonzero(component)*np.prod(delta))
    report = {"ifc_input": source or {}, "origin_m": low.tolist(), "lengths_m": lengths.tolist(),
              "requested_spacing_m": requested.tolist(), "spacing_m": delta.tolist(), "shape": shape.tolist(),
              "active_cells": int(np.count_nonzero(component)), "ifc_volume_m3": exact,
              "voxel_volume_m3": volume, "relative_volume_error": abs(volume-exact)/exact,
              "components": records, "scope": "Clasificación por centros; componentes geométricos, no plan de vertidas. Referencia volumétrica: triangulación IFC."}
    return VoxelGrid(low, lengths, delta, component, report)
