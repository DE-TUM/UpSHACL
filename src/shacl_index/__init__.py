"""Expose the :class:`ShapeIndex` singleton at package level."""

from .shape_index import ShapeIndex  # noqa: F401  (re‑export)

__all__ = ["ShapeIndex"]
