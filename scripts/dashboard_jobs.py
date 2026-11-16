"""Trabajos locales del visor para E11 y Monte Carlo E12."""

import importlib.util
import base64
from pathlib import Path
import threading
from types import SimpleNamespace
from uuid import uuid4

from scripts import monte_carlo as mc, weather_3d
from weather.snapshots import list_snapshots


OUTPUT = mc.ROOT / "results" / "visor_python"
EXAMPLES = {
    "weather": mc.ROOT / "results/weather_3d/2026-11-12T0153Z_forecast/visor_e11.json",
    "monte-carlo": mc.ROOT / "results/examples/monte_carlo_g8.json",
}
FINAL_BUNDLE = mc.ROOT / "results/final/g8_20261119_ampliada"


def final_example():
    """Empaqueta la campaña verificada y sus figuras para ambas versiones del visor."""
    comparison = FINAL_BUNDLE / "comparison.json"
    campaign = mc.read_json(comparison)
    figures = {}
    for filename, label in (
        ("duracion_riesgo", "Duración y riesgo conjunto"),
        ("cronograma", "Cronograma de vertidas"),
        ("hidratacion", "Curvas de hidratación"),
        ("clima", "Historias meteorológicas"),
        ("temperaturas_criticas", "Temperaturas críticas del escenario de verificación"),
        ("cortes_tmax", "Cortes en la máxima temperatura"),
        ("cortes_delta", "Cortes en el máximo diferencial"),
    ):
        path = FINAL_BUNDLE / "figures" / f"{filename}.png"
        if path.is_file():
            figures[label] = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"campaign":campaign,"figures":figures}
RUN_LOCK = threading.Lock()
_jobs = {}
_jobs_lock = threading.Lock()


def _sources(config):
    root = mc.ROOT / config["weather"]["snapshot_root"]
    site = config["site"]
    return {Path(row["folder"]).name: row for row in reversed(list_snapshots(root, "forecast"))
            if all(row.get(key) == site[key] for key in ("latitude", "longitude"))}


def options():
    config = mc.read_json(mc.CONFIG / "environment_g8.json")
    return {"snapshots": [{"id": name, "retrieved_at": row["retrieved_at"]}
                          for name, row in _sources(config).items()],
            "pyvista": importlib.util.find_spec("pyvista") is not None}


def _parameters(data, config):
    if not isinstance(data, dict):
        raise ValueError("Se espera un objeto JSON")
    kind = data.get("kind")
    limits = {"weather": {"hours": (1, 48)},
              "monte_carlo": {"count": (1, 32), "seed": (0, 2**32-1), "workers": (1, 4)}}
    if not isinstance(kind, str) or kind not in limits:
        raise ValueError("Parámetros del trabajo desconocidos o incompletos")
    expected = {"kind", "snapshot", "coarsen", *limits[kind]}
    if kind == "weather":
        expected.add("pyvista")
    if set(data) != expected:
        raise ValueError("Parámetros del trabajo desconocidos o incompletos")
    for key, (lo, hi) in {"coarsen": (1, 2), **limits[kind]}.items():
        if type(data[key]) is not int or not lo <= data[key] <= hi:
            raise ValueError(f"{key}: usa un entero entre {lo} y {hi}")
    snapshot = data["snapshot"]
    sources = _sources(config)
    if not isinstance(snapshot, str) or (snapshot != "synthetic" and snapshot not in sources):
        raise ValueError("Selecciona un pronóstico guardado de G8 o la serie sintética")
    if kind == "weather" and (type(data["pyvista"]) is not bool or
                              (data["pyvista"] and importlib.util.find_spec("pyvista") is None)):
        raise ValueError("Para exportar la malla 3D, instala requirements-pyvista.txt")
    return SimpleNamespace(**{k: v for k, v in data.items() if k not in {"kind", "snapshot"}},
                           snapshot=sources[snapshot]["folder"] if snapshot != "synthetic" else None,
                           synthetic=snapshot == "synthetic", start=None)


def _update(job, **changes):
    with _jobs_lock:
        _jobs[job].update(changes)


def _run(job, kind, args, config):
    try:
        folder = OUTPUT / job
        if kind == "weather":
            args.out, args.every, args.max_dt, args.no_hydration = folder, 6.0, 900.0, False
            result, _ = weather_3d.run(args, config)
            path = result / "visor_e11.json"
        else:
            args.lot, args.distributions = folder, mc.CONFIG / "monte_carlo_g8.json"
            args.hours, args.dt = 336.0, 600.0
            mc.sample(args)
            mc.run_local(folder, args.workers, lambda done: _update(job, completed=done))
            mc.aggregate(folder)
            path = folder / "aggregate.json"
        _update(job, state="done", completed=args.count if kind == "monte_carlo" else 1, path=path)
    except Exception as error:
        _update(job, state="error", error=str(error) or type(error).__name__)
    finally:
        RUN_LOCK.release()


def start(data):
    config = mc.read_json(mc.CONFIG / "environment_g8.json")
    args = _parameters(data, config)
    kind = data["kind"]
    if not RUN_LOCK.acquire(blocking=False):
        return None
    job = uuid4().hex
    try:
        with _jobs_lock:
            _jobs[job] = {"id": job, "kind": kind, "state": "running", "completed": 0,
                          "total": args.count if kind == "monte_carlo" else 1}
        threading.Thread(target=_run, args=(job, kind, args, config)).start()
    except Exception:
        with _jobs_lock:
            _jobs.pop(job, None)
        RUN_LOCK.release()
        raise
    return status(job)


def status(job):
    with _jobs_lock:
        record = _jobs[job].copy()
    path = record.pop("path", None)
    if path is not None:
        record["folder"] = path.parent.relative_to(mc.ROOT).as_posix()
    return record


def result(job):
    with _jobs_lock:
        record = _jobs[job].copy()
    if record["state"] != "done":
        raise ValueError("El resultado aún no está disponible")
    path = record["path"]
    if record["kind"] == "weather":
        return path.read_bytes()
    return {"summary": mc.read_json(path),
            "runs": [mc.read_json(mc.result_path(path.parent, index)) for index in range(record["total"])]}
