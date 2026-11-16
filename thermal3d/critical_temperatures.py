"""Extremos del hormigón activo y reconstrucción normal a 25 mm de cada cara."""

import numpy as np

from environment import SurfaceExposure


def temperature_at_depth(center, ambient, outer_r, half_cell_r, depth_m, half_cell_m):
    """Reconstrucción lineal del tramo conductivo con el flujo del borde FV."""
    return center + (ambient-center) * half_cell_r / (outer_r+half_cell_r) * (1-depth_m/half_cell_m)


class CriticalTemperatures:
    def __init__(self, concrete, origin, spacing, depth_m=.025):
        self.concrete = concrete
        self.origin = np.asarray(origin)
        self.spacing = np.asarray(spacing)
        self.depth_m = depth_m
        if not 0 <= depth_m <= min(self.spacing)/2:
            raise ValueError("La reconstrucción requiere que 25 mm quede entre la cara y el centro")
        self.active = None
        self.tmax = self.delta = None
        self.hourly = {}
        self.snapshot = None
        self._ids = np.arange(concrete.size).reshape(concrete.shape)

    def _xyz(self, cell):
        return self.origin +(np.array(cell)+.5)*self.spacing

    def _rebuild(self, active, coefficients):
        self.active = active
        self.placed = np.flatnonzero(active & self.concrete)
        self.faces = []
        for (index, bc, half_r, area), direction in zip(coefficients.faces, coefficients.face_directions):
            if not isinstance(bc, SurfaceExposure):
                continue
            mask = (area > 0) & self.concrete[index]
            if mask.any():
                cells = self._ids[index][mask]
                axis = "xyz".index(direction[0])
                resistance = np.broadcast_to(half_r, mask.shape)[mask]
                self.faces.append((cells, axis, direction, resistance, bc))

    def observe(self, time, temperature, active, coefficients):
        if active is not self.active:
            self._rebuild(active, coefficients)
        if not len(self.placed):
            return
        field = temperature.ravel()
        hot = self.placed[np.argmax(field[self.placed])]
        cold, face = np.inf, None
        for cells, axis, direction, half_r, bc in self.faces:
            values = temperature_at_depth(field[cells], bc.equivalent_ambient_c(time),
                                          bc.outer_resistance_m2k_w(time), half_r,
                                          self.depth_m, self.spacing[axis]/2)
            i = int(values.argmin())
            if values[i] < cold:
                cold, face = float(values[i]), (int(cells[i]), axis, direction, float(half_r[i]), bc)
        hour = time / 3600
        maximum = float(field[hot])
        if self.tmax is None or maximum > self.tmax["value_c"]:
            self.tmax = self._record(hot, maximum, hour)
        delta = maximum - cold if face is not None else None
        if delta is not None and (self.delta is None or delta > self.delta["value_c"]):
            cell, axis, direction, half_r, bc = face
            surface = self._record(cell, cold, hour)
            surface["xyz_m"][axis] += (self.spacing[axis]/2-self.depth_m) * (1 if direction[1]=="+" else -1)
            surface["face"] = direction
            face_c = float(temperature_at_depth(field[cell], bc.equivalent_ambient_c(time),
                                                bc.outer_resistance_m2k_w(time), half_r, 0, self.spacing[axis]/2))
            profile = [[0, face_c], [1000*self.depth_m, cold],
                       [500*self.spacing[axis], float(field[cell])]]
            self.delta = {"value_c": delta, "time_h": hour, "hot": self._record(hot, maximum, hour),
                          "surface": surface, "profile_mm_c": profile}
        if delta is not None:
            self.snapshot = {"time_h": hour, "tmax_c": maximum, "surface_c": cold, "delta_c": delta,
                             "face": face[2]}
            self.hourly.setdefault(int(hour), self.snapshot.copy())

    def _record(self, flat, value, hour):
        cell = [int(i) for i in np.unravel_index(flat, self.concrete.shape)]
        return {"value_c": value, "time_h": hour, "cell": cell, "xyz_m": self._xyz(cell).tolist()}
