"""Difusión térmica 1D: implementación docente propia del grupo G8."""

from .solver import Dirichlet, Neumann, Parameters, Robin, Solution, energy_per_area_j_m2, solve

__all__ = ["Dirichlet", "Neumann", "Parameters", "Robin", "Solution",
           "energy_per_area_j_m2", "solve"]
