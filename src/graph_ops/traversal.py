from __future__ import annotations

from rdflib import Node

from ..utils.custom_types import PathExpr
from ..utils.pathexpr_sparql_parser import path_expr_to_sparql

"""Graph‑traversal helpers that expand nodes / shapes.

*No* shapes‑graph introspection happens here – we expect the caller to
hand us the properties to follow.  This keeps the code pure and easy to
test with stubbed inputs.
"""

from typing import Dict, Generator, List, Set, Tuple
from urllib.parse import urlparse

from ..config import NODE_BATCH_SIZE, CLASS_BATCH_SIZE, virtuoso
from ..utils.sanitizer import sanitize_uri
from .crud import batch  # reuse the generic batch iterator
from ..config_dynamic import get_data_graph_uri, get_shapes_graph_uri

__all__ = [
    "is_valid_uri",
    "expand_nodes",
    "expand_shapes",
]


# ────────────────────────────────────────────────────────────────
# URI utils
# ----------------------------------------------------------------

def is_valid_uri(uri: str) -> bool:
    """Cheap URI validator: *scheme* and *netloc* must be present."""
    try:
        parsed = urlparse(uri)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────
# Node expansion (↗ via sh:node‑defined properties)
# ----------------------------------------------------------------

def expand_nodes(initial_nodes: Set[str], patterns: Set[str]) -> Set[str]:
    """
    Transitively expand *initial_nodes* over the given *properties*
    (i.e. the PathExpr predicates that occur with ``sh:node``).

    Strategy
    --------
      → Uses batched BFS to avoid Virtuoso’s “transitive start not given” error.
      → Accepts full path expressions (e.g. sequences, inverses).
    """
    if not initial_nodes or not patterns:
        return set(initial_nodes)

    print("INITIAL NODES:", initial_nodes)

    expanded = set(initial_nodes)
    frontier = set(initial_nodes)

    while frontier:
        next_frontier: Set[str] = set()
        batch = list(frontier)

        for i in range(0, len(batch), NODE_BATCH_SIZE):
            node_slice = batch[i : i + NODE_BATCH_SIZE]
            node_values = " ".join(f"<{sanitize_uri(n)}>" for n in node_slice)

            path_union = "\nUNION\n".join(
                f"{{ {pattern} }}" for pattern in patterns
            )

            q = f"""
            SELECT DISTINCT ?o
            WHERE {{
              GRAPH <{get_data_graph_uri()}> {{
                VALUES ?s {{ {node_values} }}
                {path_union}
              }}
            }}
            """
            print("EXPAND QUERY:\n", q)
            res = virtuoso.query_select(q)
            next_frontier.update(b["o"]["value"] for b in res["results"]["bindings"])

        next_frontier -= expanded
        expanded.update(next_frontier)
        frontier = next_frontier

    return expanded



# ────────────────────────────────────────────────────────────────
# Shape expansion (node‑shapes → referenced shapes)
# ----------------------------------------------------------------

def expand_shapes(initial_shapes: Set[str]) -> Tuple[Set[str], Set[str]]:
    """Recursively collect all node‑ and property‑shapes reachable.

    Returns `(node_shapes, property_shapes)`.
    """
    node_shapes: Set[str] = set(initial_shapes)
    property_shapes: Set[str] = set()
    frontier = set(initial_shapes)

    while frontier:
        next_frontier: Set[str] = set()
        for batch_shapes in batch(list(frontier), CLASS_BATCH_SIZE):
            values = " ".join(f"<{s}>" for s in batch_shapes)

            # (1) sh:property links ------------------------------------------------
            q_prop = f"""
            PREFIX sh: <http://www.w3.org/ns/shacl#>
            SELECT DISTINCT ?ps WHERE {{
              GRAPH <{get_shapes_graph_uri()}> {{
                VALUES ?s {{ {values} }}
                ?s sh:property ?ps .
              }}
            }}"""
            res_prop = virtuoso.query_select(q_prop)
            new_ps = {b["ps"]["value"] for b in res_prop["results"]["bindings"]}
            property_shapes.update(new_ps)

            # (2) nested sh:node references inside the *new* property shapes -----
            if new_ps:
                values_ps = " ".join(f"<{ps}>" for ps in new_ps)
                q_node = f"""
                PREFIX sh: <http://www.w3.org/ns/shacl#>
                SELECT DISTINCT ?ns WHERE {{
                  GRAPH <{get_shapes_graph_uri()}> {{
                    VALUES ?ps {{ {values_ps} }}
                    ?ps sh:node ?ns .
                  }}
                }}"""
                res_node = virtuoso.query_select(q_node)
                for b in res_node["results"]["bindings"]:
                    ns = b["ns"]["value"]
                    if ns not in node_shapes:
                        next_frontier.add(ns)
        frontier = next_frontier
        node_shapes.update(frontier)

    return node_shapes, property_shapes
