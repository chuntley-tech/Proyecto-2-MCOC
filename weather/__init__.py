"""Pipeline meteorológico trazable (guía G07): descarga → snapshot inmutable → serie → bordes.

* open_meteo: arma la consulta y descarga (forecast, ensemble, reanálisis/archivo,
  historical forecast y previous runs) sin tocar la respuesta.
* snapshots: guarda cada descarga en data/weather/<fecha>Z_<tipo>/ con metadata,
  hash y fecha de descarga; nunca sobrescribe.
* series: convierte un snapshot en series horarias, informa qué parte del período
  cubre y completa la cola faltante marcando el origen de cada hora.
"""

from .series import WeatherSeries, coverage, fill_tail, from_open_meteo, ensemble_members
from .snapshots import latest_before, list_snapshots, load_snapshot, save_snapshot

__all__ = ["WeatherSeries", "coverage", "fill_tail", "from_open_meteo", "ensemble_members",
           "latest_before", "list_snapshots", "load_snapshot", "save_snapshot"]
