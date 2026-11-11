"""Descarga un pronóstico de Open-Meteo y lo guarda como snapshot inmutable.

Uso (desde la raíz del repo, con internet):

    python -m scripts.fetch_weather                      # forecast 16 días, sitio docente G8
    python -m scripts.fetch_weather --kind ensemble --model gfs025 --days 35
    python -m scripts.fetch_weather --kind archive --start 2025-11-27 --end 2025-12-11

Cada ejecución crea una carpeta nueva en data/weather/; nunca reemplaza una anterior.
"""

import argparse
import json
from pathlib import Path

from weather.open_meteo import ENDPOINTS, build_request, fetch
from weather.series import coverage, from_open_meteo
from weather.snapshots import ROOT, load_snapshot, save_snapshot

ROOT_DIR = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT_DIR / "config" / "environment_g8.json"))
    parser.add_argument("--kind", default="forecast", choices=sorted(ENDPOINTS))
    parser.add_argument("--days", type=int, default=16)
    parser.add_argument("--model")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--previous-day", type=int, choices=range(1, 8),
                        help="antelación en días para --kind previous_runs")
    parser.add_argument("--out", default=str(ROOT_DIR / ROOT))
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    site = config["site"]
    request = build_request(args.kind, site["latitude"], site["longitude"], forecast_days=args.days,
                            start_date=args.start, end_date=args.end, model=args.model, previous_day=args.previous_day)
    print("Consultando:", request["url"])
    folder = save_snapshot(fetch(request), request, root=args.out)
    metadata, payload = load_snapshot(folder)
    print(f"Snapshot guardado en {folder}")
    print(f"  {metadata['status']}, {metadata['hours']} h: {metadata['first_time']} a {metadata['last_time']} UTC")
    print(f"  sha256 {metadata['sha256'][:16]}…")
    if args.kind == "forecast":
        report = coverage(from_open_meteo(payload, metadata), config["construction"]["start_utc"],
                          config["construction"]["days_after_start"])
        print(f"  Cobertura del período de construcción: {report['covered_hours']:.0f} de "
              f"{report['needed_hours']:.0f} h; faltan {report['missing_hours_at_end']:.0f} h al final")
        if not report["complete"]:
            print("  El pronóstico aún no cubre todo el período: el demo completará la cola y la marcará.")


if __name__ == "__main__":
    main()
