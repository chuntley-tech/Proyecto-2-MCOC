"""Volúmenes finitos cartesianos propios, independientes de Blender y del IFC."""

from .solver import Parameters, Solution, prepare, solve

__all__ = ["Parameters", "Solution", "prepare", "solve"]
