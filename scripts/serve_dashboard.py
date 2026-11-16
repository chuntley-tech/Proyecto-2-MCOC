"""Sirve el visor HTML local y conecta sus controles con el solver Python.

Uso: python -m scripts.serve_dashboard [--port 8765] [--open]
Solo escucha en 127.0.0.1. Los trabajos E11/E12 escriben en results/visor_python.
"""

import argparse
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import webbrowser

from thermal3d.dashboard import metadata, run_simulation
from scripts import dashboard_jobs

WEB = Path(__file__).resolve().parents[1]/"web"
RUN_LOCK = dashboard_jobs.RUN_LOCK
JOB_ROUTE = re.compile(r"/api/jobs/([a-f0-9]{32})(/result)?")
EXAMPLE_ROUTE = re.compile(r"/api/examples/(weather|monte-carlo)")
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/terrain.js": ("terrain.js", "text/javascript"), "/terrain_g8.json": ("terrain_g8.json", "application/json"),
          "/terrain_g8.jpg": ("terrain_g8.jpg", "image/jpeg"),
          "/styles.css": ("styles.css", "text/css"), "/visor_termico.html": ("../visor_termico.html", "text/html"),
          "/fonts/Inter-Variable.ttf": ("fonts/Inter-Variable.ttf", "font/ttf")}


class Handler(BaseHTTPRequestHandler):
    """API pequeña con recursos estáticos cerrados, sin lectura arbitraria de rutas."""

    def _send(self, status, body, kind="application/json", portable=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        compressed = "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 2048
        if compressed:
            body = gzip.compress(body, compresslevel=3)
        self.send_response(status)
        self.send_header("Content-Type", kind+("; charset=utf-8" if kind.startswith("text/") or kind=="application/json" else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        policy = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; worker-src blob:; img-src data: blob:; font-src data:; connect-src 'none'; frame-ancestors 'none'"
                  if portable else "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Security-Policy", policy)
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _local_request(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") not in (expected, f"localhost:{self.server.server_port}"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://{expected}", f"http://localhost:{self.server.server_port}")

    def do_GET(self):
        if not self._local_request():
            self._send(403, {"error": "Acceso local requerido"})
            return
        path = urlsplit(self.path).path
        try:
            if path in ASSETS:
                name, kind = ASSETS[path]
                self._send(200, (WEB/name).read_bytes(), kind, portable=path=="/visor_termico.html")
            elif path == "/api/meta":
                self._send(200, metadata())
            elif path == "/api/jobs/options":
                self._send(200, dashboard_jobs.options())
            elif path == "/api/examples/plans":
                self._send(200, dashboard_jobs.final_example())
            elif example := EXAMPLE_ROUTE.fullmatch(path):
                self._send(200, dashboard_jobs.EXAMPLES[example[1]].read_bytes())
            elif route := JOB_ROUTE.fullmatch(path):
                job, want_result = route.groups()
                try:
                    value = dashboard_jobs.result(job) if want_result else dashboard_jobs.status(job)
                except KeyError:
                    self._send(404, {"error": "Trabajo desconocido en esta sesión del servidor"})
                else:
                    self._send(200, value)
            else:
                self._send(404, {"error": "Recurso no encontrado"})
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            self._send(400, {"error": str(error)})

    def do_POST(self):
        if not self._local_request():
            self._send(403, {"error": "Acceso local requerido"})
            return
        path = urlsplit(self.path).path
        if path not in ("/api/run", "/api/jobs"):
            self._send(404, {"error": "Recurso no encontrado"})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self._send(415, {"error": "Use application/json"})
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 32768:
                raise ValueError("Solicitud vacía o demasiado grande")
            data = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "JSON inválido o solicitud demasiado grande"})
            return
        if path == "/api/jobs":
            try:
                job = dashboard_jobs.start(data)
                if job is None:
                    self._send(409, {"error": "Ya hay un cálculo en curso; espera a que termine"})
                else:
                    self._send(202, job)
            except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
                self._send(400, {"error": str(error)})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self._send(409, {"error": "Ya hay un cálculo en curso; espere su resultado"})
            return
        try:
            self._send(200, run_simulation(data))
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
            self._send(400, {"error": str(error)})
        finally:
            RUN_LOCK.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="abre el navegador predeterminado")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Visor térmico local: {url}", flush=True)
    print("Mantenga esta consola abierta. Ctrl+C detiene el servidor.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
