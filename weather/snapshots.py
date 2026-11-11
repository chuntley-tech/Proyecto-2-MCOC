"""Snapshots inmutables de descargas meteorológicas (G07).

data/weather/
├── 2026-11-11T1200Z_forecast/
│   ├── metadata.json      fuente, modelo, fecha de descarga, coordenadas, unidades, hash
│   └── forecast.json      respuesta original, sin modificar
└── 2026-11-20T1200Z_forecast/ …

Un pronóstico descargado una semana antes no es el mismo dato que el descargado
el día anterior. Por eso cada descarga es una carpeta nueva, nunca se
sobrescribe, y su hash permite comprobar que no se editó. Con latest_before se
reproduce exactamente qué se sabía en el momento de una decisión.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .open_meteo import STATUS

ROOT = Path("data/weather")


def _utc(moment):
    if moment is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("La fecha de descarga debe tener zona horaria (UTC)")
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def save_snapshot(raw: bytes, request: dict, root=ROOT, retrieved_at=None) -> Path:
    """Guarda la respuesta tal cual y su metadata. Falla si la carpeta ya existe."""
    payload = json.loads(raw)
    if not payload.get("hourly", {}).get("time"):
        raise ValueError("La respuesta no tiene serie horaria; revise la consulta")
    moment = _utc(retrieved_at)
    kind = request["kind"]
    folder = Path(root) / f"{moment:%Y-%m-%dT%H%M}Z_{kind}"
    folder.mkdir(parents=True, exist_ok=False)          # inmutable: nunca reescribir un snapshot
    data_name = f"{kind}.json"
    (folder / data_name).write_bytes(raw)
    hourly = payload["hourly"]
    variables = [name for name in hourly if name != "time"]
    metadata = {
        "source": "Open-Meteo (https://open-meteo.com/)",
        "kind": kind,
        "status": STATUS.get(kind, kind),
        "model": request["params"].get("models", "seamless (elección automática de Open-Meteo)"),
        "retrieved_at": moment.isoformat().replace("+00:00", "Z"),
        "request_url": request["url"],
        "latitude": request["params"]["latitude"],
        "longitude": request["params"]["longitude"],
        "grid_latitude": payload.get("latitude"),
        "grid_longitude": payload.get("longitude"),
        "timezone": payload.get("timezone", request["params"].get("timezone")),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
        "variables": variables,
        "units": payload.get("hourly_units", {}),
        "first_time": hourly["time"][0],
        "last_time": hourly["time"][-1],
        "hours": len(hourly["time"]),
        "file": data_name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "note": "Respuesta original sin modificar. shortwave_radiation es la media de la hora anterior.",
    }
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder


def load_snapshot(folder):
    """Devuelve (metadata, respuesta). Comprueba que el archivo no fue modificado."""
    folder = Path(folder)
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    raw = (folder / metadata["file"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError(f"{folder}: el archivo cambió después de descargarlo (hash distinto)")
    return metadata, json.loads(raw)


def list_snapshots(root=ROOT, kind=None):
    """Metadata de los snapshots, ordenados por fecha de descarga."""
    rows = []
    for path in sorted(Path(root).glob("*/metadata.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if kind is None or metadata["kind"] == kind:
            rows.append({**metadata, "folder": str(path.parent)})
    return sorted(rows, key=lambda row: row["retrieved_at"])


def latest_before(decision_time, root=ROOT, kind="forecast", *, coordinates=None):
    """Carpeta del último snapshot descargado ANTES de decision_time (lo que se sabía)."""
    limit = _utc(decision_time)
    candidates = [
        row for row in list_snapshots(root, kind)
        if _utc(row["retrieved_at"]) <= limit
        and (coordinates is None or (row["latitude"], row["longitude"]) == coordinates)
    ]
    if not candidates:
        raise LookupError(f"No hay snapshots de tipo {kind} descargados antes de {limit.isoformat()}")
    return Path(candidates[-1]["folder"])
