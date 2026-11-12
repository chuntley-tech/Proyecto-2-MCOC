"""Exportación VTK de grillas de voxeles (G06), sin dependencias además de NumPy.

Escribe VTK XML ImageData (.vti) con datos por celda en binario "raw" anexado y
una colección .pvd para series de tiempo. ParaView y PyVista los abren
directamente (pyvista.read("archivo.vti"), o File > Open en ParaView).

La grilla del solver es centrada en celdas: el arreglo T[i, j, k] corresponde a
la celda i, j, k. En VTK, ImageData con dimensions = shape + 1 (puntos) tiene
exactamente shape celdas, y los datos de celda se guardan con x variando más
rápido (orden Fortran), igual que T.ravel(order="F") en la guía G06.
"""

from pathlib import Path
from xml.sax.saxutils import quoteattr
import struct

import numpy as np

VTK_TYPES = {np.dtype("float32"): "Float32", np.dtype("float64"): "Float64", np.dtype("int8"): "Int8",
             np.dtype("uint8"): "UInt8", np.dtype("int16"): "Int16", np.dtype("int32"): "Int32",
             np.dtype("int64"): "Int64"}


def _as_3d(array):
    array = np.asarray(array)
    if array.ndim == 2:
        array = array[:, :, None]
    if array.ndim != 3:
        raise ValueError("Se esperaba un campo 2D o 3D")
    return array


def write_vti(path, cell_data, spacing_m, origin_m=(0.0, 0.0, 0.0), field_data=None):
    """Escribe un .vti con campos de celda {nombre: arreglo con la forma de la grilla}.

    field_data: escalares globales (p. ej. TimeValue en horas) que quedan dentro
    del archivo. Los textos de trazabilidad (snapshot, hash) van en un JSON aparte.
    """
    if not cell_data:
        raise ValueError("Se requiere al menos un campo de celda")
    arrays = {name: _as_3d(value) for name, value in cell_data.items()}
    shapes = {a.shape for a in arrays.values()}
    if len(shapes) != 1:
        raise ValueError(f"Todos los campos deben tener la misma forma; hay {shapes}")
    shape = shapes.pop()
    spacing = [float(v) for v in np.atleast_1d(np.asarray(spacing_m, dtype=float))]
    origin = [float(v) for v in np.atleast_1d(np.asarray(origin_m, dtype=float))]
    if len(spacing) == 1:
        spacing = spacing * 3
    while len(spacing) < 3:
        spacing.append(1.0)
    while len(origin) < 3:
        origin.append(0.0)
    extent = f"0 {shape[0]} 0 {shape[1]} 0 {shape[2]}"

    blocks, headers, offset = [], [], 0
    for name, array in arrays.items():
        if array.dtype == bool:
            array = array.astype(np.uint8)
        if array.dtype not in VTK_TYPES:
            array = array.astype(np.float64)
        data = np.ascontiguousarray(array.ravel(order="F")).astype(array.dtype.newbyteorder("<"), copy=False).tobytes()
        headers.append(f'        <DataArray type="{VTK_TYPES[array.dtype]}" Name={quoteattr(name)} '
                       f'format="appended" offset="{offset}"/>')
        blocks.append(struct.pack("<I", len(data)) + data)
        offset += 4 + len(data)

    fields = []
    for name, value in (field_data or {}).items():
        values = np.atleast_1d(np.asarray(value, dtype=float))
        fields.append(f'      <DataArray type="Float64" Name={quoteattr(name)} NumberOfTuples="{values.size}" '
                      f'format="ascii">{" ".join(repr(float(v)) for v in values)}</DataArray>')

    first = next(iter(arrays))
    header = "\n".join([
        '<?xml version="1.0"?>',
        '<VTKFile type="ImageData" version="1.0" byte_order="LittleEndian" header_type="UInt32">',
        f'  <ImageData WholeExtent="{extent}" Origin="{origin[0]!r} {origin[1]!r} {origin[2]!r}" '
        f'Spacing="{spacing[0]!r} {spacing[1]!r} {spacing[2]!r}">',
        *(["    <FieldData>", *fields, "    </FieldData>"] if fields else []),
        f'    <Piece Extent="{extent}">',
        f'      <CellData Scalars={quoteattr(first)}>',
        *headers,
        "      </CellData>",
        "    </Piece>",
        "  </ImageData>",
        '  <AppendedData encoding="raw">',
        "   _",
    ])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(header.encode("utf-8"))
        for block in blocks:
            stream.write(block)
        stream.write(b"\n  </AppendedData>\n</VTKFile>\n")
    return path


def write_pvd(path, entries):
    """Colección temporal de ParaView: entries = [(tiempo, ruta relativa del .vti), ...]."""
    path = Path(path)
    lines = ['<?xml version="1.0"?>', '<VTKFile type="Collection" version="1.0" byte_order="LittleEndian">',
             "  <Collection>"]
    for time, file in entries:
        lines.append(f'    <DataSet timestep="{float(time)!r}" group="" part="0" file={quoteattr(str(file))}/>')
    lines += ["  </Collection>", "</VTKFile>", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def read_vti(path):
    """Lector mínimo de los .vti escritos aquí (para pruebas y para revisar sin PyVista)."""
    import re
    raw = Path(path).read_bytes()
    marker = raw.index(b'<AppendedData encoding="raw">')
    start = raw.index(b"_", marker) + 1
    header = raw[:marker].decode("utf-8")
    extent = [int(v) for v in re.search(r'WholeExtent="([^"]+)"', header).group(1).split()]
    shape = (extent[1] - extent[0], extent[3] - extent[2], extent[5] - extent[4])
    spacing = [float(v) for v in re.search(r'Spacing="([^"]+)"', header).group(1).split()]
    origin = [float(v) for v in re.search(r'Origin="([^"]+)"', header).group(1).split()]
    lookup = {v: k for k, v in VTK_TYPES.items()}
    cells = {}
    for kind, name, offset in re.findall(r'<DataArray type="(\w+)" Name="([^"]+)" format="appended" offset="(\d+)"',
                                         header):
        position = start + int(offset)
        size = struct.unpack("<I", raw[position:position + 4])[0]
        values = np.frombuffer(raw[position + 4:position + 4 + size], dtype=lookup[kind].newbyteorder("<"))
        cells[name] = values.reshape(shape, order="F")
    fields = {}
    for kind, name, text in re.findall(r'<DataArray type="(\w+)" Name="([^"]+)" NumberOfTuples="\d+" '
                                       r'format="ascii">([^<]*)</DataArray>', header):
        values = [float(v) for v in text.split()]
        fields[name] = values[0] if len(values) == 1 else values
    return {"shape": shape, "spacing": spacing, "origin": origin, "cells": cells, "fields": fields}
