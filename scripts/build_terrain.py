"""Recorta un GeoTIFF público Copernicus GLO-30 para el visor G8.

Uso: python -m scripts.build_terrain ruta/al/GeoTIFF.tif
La descarga de origen y el proceso se documentan en docs/VISOR_HTML.md.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TILE = "Copernicus_DSM_COG_10_S42_00_W074_00_DEM"
SOURCE = f"https://copernicus-dem-30m.s3.amazonaws.com/{TILE}/{TILE}.tif"
EXTENT_M = 18000
SAMPLES = 201


def build(input_path, output):
    site = json.loads((ROOT/"config/case_g8.json").read_text(encoding="utf-8"))["site"]
    lat, lon = site["latitude"], site["longitude"]
    # Aproximación local WGS84, con ejes este/norte en metros en el punto G8.
    phi = np.deg2rad(lat)
    a, eccentricity_squared = 6378137.0, 0.0066943799901413165
    curvature = np.sqrt(1-eccentricity_squared*np.sin(phi)**2)
    meters_lon = np.deg2rad(1)*a*np.cos(phi)/curvature
    meters_lat = np.deg2rad(1)*a*(1-eccentricity_squared)/curvature**3
    offsets = np.linspace(-EXTENT_M/2, EXTENT_M/2, SAMPLES)
    with Image.open(input_path) as tile:
        sx, sy, _ = tile.tag_v2[33550]
        i, j, _, west, north, _ = tile.tag_v2[33922]
        keys = tuple(tile.tag_v2[34735])[4:]
        geokeys = {keys[p]: keys[p+3] for p in range(0, len(keys), 4) if keys[p+1] == 0}
        if geokeys.get(2048) != 4326 or geokeys.get(1025) != 2 or tile.mode != "F":
            raise ValueError("Se requiere Copernicus COG WGS84 con alturas de punto")
        columns = i+(lon+offsets/meters_lon-west)/sx
        rows = j+(north-lat-offsets/meters_lat)/sy
        left, top = int(np.floor(columns.min())), int(np.floor(rows.min()))
        right, bottom = int(np.floor(columns.max()))+2, int(np.floor(rows.max()))+2
        if left < 0 or top < 0 or right > tile.width or bottom > tile.height:
            raise ValueError("El GeoTIFF no cubre todo el recorte G8")
        patch = np.asarray(tile.crop((left, top, right, bottom)), dtype=float)
        nodata = tile.tag_v2.get(42113)
        if not np.isfinite(patch).all() or (nodata is not None and np.any(patch == float(nodata))):
            raise ValueError("El recorte contiene alturas sin datos")
    x, y = np.meshgrid(columns-left, rows-top)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    dx, dy = x-ix, y-iy
    elevation = ((1-dy)*((1-dx)*patch[iy, ix]+dx*patch[iy, ix+1])
                 + dy*((1-dx)*patch[iy+1, ix]+dx*patch[iy+1, ix+1]))
    bounds = [lon+offsets[0]/meters_lon, lat+offsets[0]/meters_lat,
              lon+offsets[-1]/meters_lon, lat+offsets[-1]/meters_lat]
    data = {"latitude": lat, "longitude": lon, "extent_m": EXTENT_M, "samples": SAMPLES,
            "bounds_wgs84": [round(value, 9) for value in bounds],
            "source": SOURCE, "source_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "elevation_m": np.round(elevation, 1).ravel().tolist()}
    output.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False)+"\n", encoding="utf-8")
    print(f"Recorte G8: {SAMPLES} × {SAMPLES} muestras; cota G8 {elevation[SAMPLES//2, SAMPLES//2]:.1f} m")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geotiff", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT/"web/terrain_g8.json")
    args = parser.parse_args()
    build(args.geotiff, args.output)
