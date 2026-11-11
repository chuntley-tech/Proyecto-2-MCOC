"""Cliente mínimo de Open-Meteo (G07). Solo arma la URL y descarga los bytes.

Variables pedidas, y por qué (G07: no pedir variables que ninguna ecuación usa):

* temperature_2m [°C]: temperatura del aire en Robin / sol-aire. Obligatoria.
* wind_speed_10m [m/s]: h = 5,7 + 3,8·v en la película convectiva.
* shortwave_radiation [W/m²]: radiación de onda corta (GHI), media de la hora
  ANTERIOR a la marca de tiempo; entra como a·G en la temperatura sol-aire.

Se pide timezone=GMT para que las horas no tengan ambigüedad por el cambio de
hora en Chile; la hora local se calcula al mostrar resultados.
"""

from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINTS = {
    "forecast": "https://api.open-meteo.com/v1/forecast",                       # pronóstico determinista (≤ 16 días)
    "ensemble": "https://ensemble-api.open-meteo.com/v1/ensemble",              # miembros del ensemble
    "archive": "https://archive-api.open-meteo.com/v1/archive",                 # reanálisis (pasado)
    "historical_forecast": "https://historical-forecast-api.open-meteo.com/v1/forecast",
    "previous_runs": "https://previous-runs-api.open-meteo.com/v1/forecast",
}
STATUS = {
    "forecast": "pronóstico determinista",
    "ensemble": "pronóstico por ensemble",
    "archive": "reanálisis (no es observación directa ni pronóstico)",
    "historical_forecast": "pronósticos pasados archivados",
    "previous_runs": "corridas anteriores del pronóstico (por antelación)",
}
VARIABLES = ("temperature_2m", "wind_speed_10m", "shortwave_radiation")


def build_request(kind, latitude, longitude, *, forecast_days=16, start_date=None, end_date=None,
                  model=None, variables=VARIABLES, previous_day=None):
    """Devuelve {'kind', 'url', 'params'}: la consulta queda escrita en la metadata."""
    if kind not in ENDPOINTS:
        raise ValueError(f"Tipo desconocido {kind!r}; use uno de {sorted(ENDPOINTS)}")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordenadas fuera de rango")
    if previous_day is not None:
        if kind != "previous_runs" or previous_day not in range(1, 8):
            raise ValueError("previous_day debe estar entre 1 y 7 y requiere previous_runs")
        variables = tuple(f"{name}_previous_day{previous_day}" for name in variables)
    params = {"latitude": latitude, "longitude": longitude, "hourly": ",".join(variables),
              "wind_speed_unit": "ms", "timezone": "GMT"}
    if kind in ("archive", "historical_forecast"):
        if not (start_date and end_date):
            raise ValueError(f"{kind} requiere start_date y end_date (AAAA-MM-DD)")
        params.update(start_date=start_date, end_date=end_date)
    else:
        maximum = 36 if kind == "ensemble" else 16
        if not 1 <= int(forecast_days) <= maximum:
            raise ValueError(f"{kind}: forecast_days debe estar entre 1 y {maximum}")
        params["forecast_days"] = int(forecast_days)
    if model:
        params["models"] = model
    elif kind == "ensemble":
        raise ValueError("ensemble requiere model, por ejemplo gfs025 o ecmwf_ifs025")
    return {"kind": kind, "url": f"{ENDPOINTS[kind]}?{urlencode(params)}", "params": params}


def fetch(request, timeout_s=60):
    """Descarga y devuelve los bytes tal como llegan (se guardan sin modificar)."""
    message = Request(request["url"], headers={"User-Agent": "Proyecto-2-MCOC (curso UANDES)"})
    with urlopen(message, timeout=timeout_s) as response:
        if response.status != 200:
            raise RuntimeError(f"Open-Meteo respondió {response.status}")
        return response.read()
