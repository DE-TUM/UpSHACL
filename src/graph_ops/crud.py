from __future__ import annotations

from rdflib import Node

"""Basic create/read/update/delete helpers that talk to Virtuoso.

* **stateless** – no caching, no shapes‑graph knowledge
* All heavy shape‑specific logic lives in ``shape_index``.
"""

from typing import Generator, List
import random

from src.config import (
    virtuoso,
    MAX_BATCH_SIZE,  # VALUES batch size for large SELECTs
)
from src.utils.custom_types import Triple
from src.utils.sanitizer import build_sparql_triples, build_sparql_triples_nodes

__all__ = [
    "batch",
    "cleanup_temp_graphs",
    "count_triples_in_graph",
    "sample_triples_from_graph",
    "insert_triples",
    "delete_triples",
]

# ────────────────────────────────────────────────────────────────
# helper: batching iterator
# ────────────────────────────────────────────────────────────────

def batch(values: List[str], size: int) -> Generator[List[str], None, None]:
    """Yield successive *non‑empty* slices of *values* of length ≤ *size*."""

    for i in range(0, len(values), size):
        yield values[i : i + size]


# ────────────────────────────────────────────────────────────────
# housekeeping helpers
# ────────────────────────────────────────────────────────────────

def cleanup_temp_graphs() -> None:
    """Drop the well‑known temp graphs created by the pipeline."""

    for g in ("http://temp.org/data", "http://temp.org/shapes"):
        virtuoso.update(f"DROP SILENT GRAPH <{g}>")
    print("[crud] dropped temp graphs")


def count_triples_in_graph(graph_uri: str) -> int:
    q = f"SELECT (COUNT(*) AS ?c) WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    res = virtuoso.query(q)
    count = int(res["results"]["bindings"][0]["c"]["value"])
    print(f"[crud] <{graph_uri}> -> {count} triples")
    return count


# ────────────────────────────────────────────────────────────────
# random sampling – used by run_experiments
# ────────────────────────────────────────────────────────────────

def sample_triples_from_graph(graph_uri: str, sample_size: int) -> List[Triple]:
    """Return *sample_size* random triples from *graph_uri* (or fewer)."""

    # total count -----------------------------------------------------------
    cnt_q = f"SELECT (COUNT(*) AS ?c) FROM <{graph_uri}> WHERE {{ ?s ?p ?o }}"
    total = int(virtuoso.query_select(cnt_q)["results"]["bindings"][0]["c"]["value"])
    if total == 0:
        print("[crud] sample request on empty graph - 0 triples")
        return []

    offset = random.randint(0, max(0, total - sample_size))
    limit = min(sample_size, total)

    q = f"""
    SELECT ?s ?p ?o
    FROM <{graph_uri}>
    WHERE {{ ?s ?p ?o }}
    OFFSET {offset}
    LIMIT {limit}
    """

    res = virtuoso.query_select(q)
    triples: List[Triple] = []
    for row in res["results"]["bindings"]:
        s = row["s"]["value"]
        p = row["p"]["value"]
        o_val = row["o"]["value"]
        o_type = row["o"].get("type", "literal")
        if o_type == "uri":
            obj = (o_val, "uri", None)
        elif o_val.startswith("_:"):
            obj = (o_val, "bnode", None)
        else:
            obj = (o_val, "literal", None)
        triples.append((s, p, obj))

    print(f"[crud] sampled {len(triples)} / {limit} triples from <{graph_uri}>")
    return triples


# ────────────────────────────────────────────────────────────────
# mutating helpers – chunked INSERT / DELETE
# ────────────────────────────────────────────────────────────────

# escaped braces → literal braces in SPARQL template ------------------------
_DELETE_TMPL = (
    """
DELETE DATA {{
  GRAPH <{graph}> {{
    {triples}
  }}
}}"""
)

_INSERT_TMPL = (
    """
INSERT DATA {{
  GRAPH <{graph}> {{
    {triples}
  }}
}}"""
)


def _chunked_update(template: str, graph_uri: str, triples: List[(Node, Node, Node)], *, chunk: int = 500) -> None:
    data = build_sparql_triples_nodes(triples)
    for part in batch(data, chunk):
        virtuoso.update(template.format(graph=graph_uri, triples=" ".join(part)))


def insert_triples(graph_uri: str, triples: List[(Node, Node, Node)]):
    if not triples:
        print("[crud] insert_triples - nothing to do")
        return
    print(f"[crud] inserting {len(triples)} triples into <{graph_uri}>")
    _chunked_update(_INSERT_TMPL, graph_uri, triples)


def delete_triples(graph_uri: str, triples: List[Triple]):
    if not triples:
        print("[crud] delete_triples - nothing to do")
        return
    print(f"[crud] deleting {len(triples)} triples from <{graph_uri}>")
    _chunked_update(_DELETE_TMPL, graph_uri, triples)
