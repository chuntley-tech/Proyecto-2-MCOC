"""Construye un HTML autónomo con CSS, JavaScript, worker y voxeles IFC incluidos.

Uso: python -m scripts.build_dashboard
El archivo visor_termico.html puede copiarse y abrirse sin Python, servidor,
Internet ni bibliotecas externas. Regenerarlo incorpora un IFC modificado.
"""

import argparse
import base64
import json
from pathlib import Path

import numpy as np

from thermal3d.dashboard import BOUNDS, ROOT, _grid, _identity, metadata


def build_pack(resolutions=(0.5, 0.25, 0.2)):
    """Captura una única versión del IFC y tres máscaras con origen/unidades SI."""
    path, fingerprint = _identity()
    meta = metadata()
    if meta["ifc"]["sha256"] != fingerprint:
        raise ValueError("El IFC cambió durante la exportación")
    grids = {}
    for resolution in resolutions:
        grid = _grid(path, fingerprint, resolution)
        grids[str(resolution)] = {"shape": list(grid.component.shape), "origin_m": grid.origin_m.tolist(),
                                  "lengths_m": grid.lengths_m.tolist(), "spacing_m": grid.spacing_m.tolist(),
                                  "active_indices": np.flatnonzero(grid.active).tolist()}
    if _identity()[1] != fingerprint:
        raise ValueError("El IFC cambió durante la exportación; vuelva a generar el HTML")
    return {"meta": meta, "bounds": BOUNDS, "grids": grids,
            "format_version": 1, "scope": "Snapshot de la geometría IFC y cálculo térmico sintético en navegador"}


def build(output):
    """Incrusta todos los recursos; el resultado no realiza solicitudes HTTP."""
    web = ROOT/"web"
    pack = json.dumps(build_pack(), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    html = (web/"index.html").read_text(encoding="utf-8")
    css = (web/"styles.css").read_text(encoding="utf-8")
    font = base64.b64encode((web/"fonts/Inter-Variable.ttf").read_bytes()).decode("ascii")
    css = css.replace("/fonts/Inter-Variable.ttf", "data:font/ttf;base64,"+font)
    html = html.replace('<link rel="stylesheet" href="/styles.css">', '<style>\n'+css+'\n</style>')
    html = html.replace('<script src="/app.js" defer></script>', '')
    policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; worker-src blob:; img-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; object-src 'none'"
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="'+policy+'">')
    html = html.replace('href="/"', 'href="#"')
    worker = (web/"solver_worker.js").read_text(encoding="utf-8").replace('</script', '<\\/script')
    app = (web/"app.js").read_text(encoding="utf-8").replace('</script', '<\\/script')
    embedded = ('<script id="mcoc-pack" type="application/json">'+pack+'</script>\n'
                '<script id="mcoc-worker" type="text/plain">'+worker+'</script>\n<script>\n'+app+'\n</script>')
    license_text = (web/"fonts/OFL.txt").read_text(encoding="utf-8").replace("<", "\\u003c")
    embedded += '\n<script id="mcoc-font-license" type="text/plain">'+license_text+'</script>'
    html = html.replace('</body>', embedded+'\n</body>')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(line.rstrip() for line in html.splitlines())+"\n", encoding="utf-8")
    print(f"HTML portátil generado: {output} ({output.stat().st_size/1_000_000:.2f} MB)")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"visor_termico.html")
    build(parser.parse_args().output)
