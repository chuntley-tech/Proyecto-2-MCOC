"""Genera, ejecuta y agrega lotes Monte Carlo de E12 sin depender de Slurm."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

import numpy as np

from scripts import e12_case, weather_3d
from scripts.voxelize_foundation import case_ifc
from weather.snapshots import load_snapshot


ROOT = e12_case.ROOT_DIR
CONFIG = ROOT / "config"
FIELDS = ("placement_c", "theta_inf_c", "tau_h")
METRICS = ("tmax_c", "delta_t_max_c")
THRESHOLDS = (70.0, 20.0)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        except BaseException:
            stream.close()
            temporary.unlink()
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_ifc_hash():
    path, _ = case_ifc(CONFIG / "case_g8.json")
    return digest(path)


def code_fingerprint():
    """Identifica los archivos Python usados, incluso si hay cambios locales."""
    paths = [path for folder in ("scripts", "thermal1d", "thermal3d", "environment", "weather")
             for path in (ROOT / folder).glob("*.py")]
    paths.extend((ROOT / "requirements.txt", CONFIG / "case_g8.json"))
    hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(
        path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for path in paths}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("ascii")).hexdigest()


def sample(args):
    if args.count < 1 or args.seed < 0:
        raise ValueError("Cantidad positiva y semilla no negativa requeridas")
    lot = args.lot.resolve()
    if lot.exists():
        raise FileExistsError(f"El lote ya existe: {lot}. Usa una carpeta nueva.")
    if args.synthetic and args.snapshot:
        raise ValueError("Elige un snapshot o clima sintético")
    config = read_json(CONFIG / "environment_g8.json")
    construction = read_json(CONFIG / "construction_g8.json")
    settings = read_json(args.distributions)
    bounds = settings["uniform"]
    if set(bounds) != set(FIELDS):
        raise ValueError(f"Los parámetros esperados son {', '.join(FIELDS)}")
    for name in FIELDS:
        lo, hi = bounds[name]
        if (not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi
                or lo <= (-273.15 if name == "placement_c" else 0)):
            raise ValueError(f"Intervalo inválido: {name}")
    if (not all(math.isfinite(v) and v > 0 for v in (args.hours, args.dt))
            or not 1 <= args.coarsen <= 4):
        raise ValueError("Duración y dt positivos, factor de malla entre 1 y 4")
    if args.hours * 3600 <= max(row["start_s"] for row in construction["pours"]):
        raise ValueError("La duración debe permitir completar todas las vertidas")
    snapshot = sha = None
    if not args.synthetic:
        folder = weather_3d.choose_snapshot(ROOT / config["weather"]["snapshot_root"],
                                             config["site"], args.snapshot).resolve()
        metadata, _ = load_snapshot(folder)
        namespace = SimpleNamespace(snapshot=folder, synthetic=False, start=None)
        e12_case.load_weather(config, namespace, args.hours)
        snapshot = str(folder.relative_to(ROOT)) if folder.is_relative_to(ROOT) else str(folder)
        sha = metadata["sha256"]
    rng = np.random.Generator(np.random.PCG64(args.seed))
    values = rng.uniform([bounds[k][0] for k in FIELDS], [bounds[k][1] for k in FIELDS],
                         size=(args.count, len(FIELDS)))
    manifest = {
        "format": "mcoc-monte-carlo-v1", "seed": args.seed, "random_generator": "PCG64",
        "numpy_version": np.__version__, "code_head": e12_case.git_commit(),
        "code_sha256": code_fingerprint(),
        "distributions": settings, "environment": config, "construction": construction,
        "ifc_sha256": current_ifc_hash(), "weather_sha256": sha, "thresholds_c": dict(zip(METRICS, THRESHOLDS)),
        "simulation": {"hours": args.hours, "dt": args.dt, "coarsen": args.coarsen,
                       "snapshot": snapshot, "synthetic": args.synthetic, "start": None},
        "samples": [dict(zip(FIELDS, row.tolist())) for row in values],
    }
    lot.mkdir(parents=True, exist_ok=False)
    write_json(lot / "manifest.json", manifest)
    return args.count


def load_manifest(lot):
    path = lot / "manifest.json"
    manifest = read_json(path)
    if manifest["format"] != "mcoc-monte-carlo-v1":
        raise ValueError("Formato de manifiesto incompatible")
    return manifest, digest(path)


def result_path(lot, index):
    return lot / "runs" / f"{index:06d}.json"


def worker(lot, index):
    manifest, fingerprint = load_manifest(lot)
    if not 0 <= index < len(manifest["samples"]):
        raise ValueError(f"Índice fuera del manifiesto: {index}")
    target = result_path(lot, index)
    if target.is_file():
        existing = read_json(target)
        if existing["manifest_sha256"] == fingerprint and existing["sample_id"] == index:
            return
        raise ValueError(f"Resultado de otra muestra o manifiesto: {target}")
    if current_ifc_hash() != manifest["ifc_sha256"]:
        raise ValueError("El IFC difiere del registrado en el manifiesto")
    if code_fingerprint() != manifest["code_sha256"] or np.__version__ != manifest["numpy_version"]:
        raise ValueError("El código o la versión de NumPy difieren del manifiesto")
    simulation = SimpleNamespace(**manifest["simulation"])
    if simulation.snapshot:
        simulation.snapshot = ROOT / simulation.snapshot
        metadata, _ = load_snapshot(simulation.snapshot)
        if metadata["sha256"] != manifest["weather_sha256"]:
            raise ValueError("El pronóstico difiere del registrado en el manifiesto")

    params = manifest["samples"][index]
    construction = deepcopy(manifest["construction"])
    construction["hydration"].update(theta_inf_c=params["theta_inf_c"], tau_h=params["tau_h"])
    for pour in construction["pours"]:
        pour["placement_c"] = params["placement_c"]
    metrics = e12_case.run(simulation, manifest["environment"], construction, metrics_only=True)
    if metrics["ifc_sha256"] != manifest["ifc_sha256"] or metrics["weather_sha256"] != manifest["weather_sha256"]:
        raise ValueError("Los insumos cambiaron durante la ejecución")
    write_json(target, {"sample_id": index, "manifest_sha256": fingerprint, "parameters": params,
                        "metrics": metrics})


def aggregate(lot):
    manifest, fingerprint = load_manifest(lot)
    count = len(manifest["samples"])
    missing = [i for i in range(count) if not result_path(lot, i).is_file()]
    if missing:
        raise ValueError(f"Faltan {len(missing)} de {count} resultados. Primeros índices: {missing[:12]}")
    values = {name: [] for name in METRICS}
    balance = []
    for i, params in enumerate(manifest["samples"]):
        row = read_json(result_path(lot, i))
        if row["sample_id"] != i or row["manifest_sha256"] != fingerprint or row["parameters"] != params:
            raise ValueError(f"Resultado incompatible con el manifiesto: {i}")
        metrics = row["metrics"]
        for name in METRICS:
            values[name].append(metrics[name])
        balance.append(metrics["energy_balance_relative"])
    matrix = np.array([values[name] for name in METRICS], dtype=float)
    if not np.isfinite(matrix).all() or not np.isfinite(balance).all():
        raise ValueError("El lote contiene métricas no finitas")
    stats = {}
    fail = []
    for name, column in zip(METRICS, matrix):
        limit = manifest["thresholds_c"][name]
        exceeds = column > limit
        fail.append(exceeds)
        stats[name] = {"threshold_c": limit, "mean_c": float(column.mean()),
                       "percentiles_c": dict(zip(("p05", "p50", "p95"), np.percentile(column, [5, 50, 95]).tolist())),
                       "exceedances": int(exceeds.sum()), "exceedance_fraction": float(exceeds.mean())}
    any_failure = np.logical_or.reduce(fail)
    summary = {"manifest_sha256": fingerprint, "samples": count, **stats,
               "any_exceedances": int(any_failure.sum()), "any_exceedance_fraction": float(any_failure.mean()),
               "max_energy_balance_relative": max(balance)}
    write_json(lot / "aggregate.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("sample", help="congela los insumos y crea las muestras")
    task = commands.add_parser("run", help="ejecuta una muestra")
    local = commands.add_parser("local", help="ejecuta el lote en paralelo en este equipo")
    combine = commands.add_parser("aggregate", help="agrega un lote completo")
    for command in (generate, task, local, combine):
        command.add_argument("lot", type=Path)
    generate.add_argument("--count", type=int, required=True)
    generate.add_argument("--seed", type=int, default=2026)
    generate.add_argument("--hours", type=float, default=336)
    generate.add_argument("--dt", type=float, default=600)
    generate.add_argument("--coarsen", type=int, default=1)
    generate.add_argument("--distributions", type=Path, default=CONFIG / "monte_carlo_g8.json")
    generate.add_argument("--snapshot", type=Path)
    generate.add_argument("--synthetic", action="store_true")
    task.add_argument("index", type=int)
    local.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    try:
        if args.command == "sample":
            print(f"Muestras generadas: {sample(args)}")
        elif args.command == "run":
            worker(args.lot, args.index)
            print(result_path(args.lot, args.index))
        elif args.command == "local":
            manifest, _ = load_manifest(args.lot)
            count = len(manifest["samples"])
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                for _ in executor.map(worker, [args.lot] * count, range(count)):
                    pass
            print(f"Resultados disponibles: {count}")
        else:
            print(json.dumps(aggregate(args.lot), indent=2))
    except (ValueError, OSError, KeyError, LookupError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
