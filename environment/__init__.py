"""Condiciones de borde ambientales: aire, viento, sol, moldaje, aislación y suelo (E10).

El solver no sabe de clima: recibe objetos de borde que entregan, para cada
instante, una temperatura equivalente y una resistencia exterior. Este paquete
los construye a partir de una serie meteorológica (paquete `weather`) y de un
cronograma de capas (moldaje que se retira, aislación que se agrega).
"""

from .surface import (FORMWORK_PLYWOOD_18MM, INSULATION_BLANKET_25MM, Layer, LayerSchedule, Region, SurfaceMap,
                      SurfaceExposure, convection_h, wind_at_height)
from .ground import SoilModel, add_soil_layer

__all__ = ["FORMWORK_PLYWOOD_18MM", "INSULATION_BLANKET_25MM", "Layer", "LayerSchedule", "Region", "SurfaceMap",
           "SurfaceExposure", "convection_h", "wind_at_height", "SoilModel", "add_soil_layer"]
