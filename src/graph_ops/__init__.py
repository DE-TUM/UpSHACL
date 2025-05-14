"""Public façade for the *graph_ops* package.

The sub-modules are imported eagerly so `graph_ops.` users see a flat API
layer, e.g.::

    from graph_ops import compute_affected_pairs, expand_nodes

If the modules live at the top-level (because the repo hasn’t been
re-structured yet) the fallback `ImportError` handler dynamically loads
them so the import still works.
"""

from importlib import import_module
import sys as _sys

_submods = ("crud", "traversal", "delta")

for _name in _submods:
    try:
        globals()[_name] = import_module(f"{__name__}.{_name}")
    except ImportError:  # fallback if files are still top-level
        globals()[_name] = import_module(_name)

# Re-export the most commonly used symbols ----------------------------------
from .crud import (
    batch,
    cleanup_temp_graphs,
    count_triples_in_graph,
    sample_triples_from_graph,
    insert_triples,
    delete_triples,
)
from .traversal import is_valid_uri, expand_nodes, expand_shapes
from .delta import compute_affected_pairs, build_reduced_graphs

__all__ = [
    # crud
    "batch",
    "cleanup_temp_graphs",
    "count_triples_in_graph",
    "sample_triples_from_graph",
    "insert_triples",
    "delete_triples",
    # traversal
    "is_valid_uri",
    "expand_nodes",
    "expand_shapes",
    # delta
    "compute_affected_pairs",
    "build_reduced_graphs",
]