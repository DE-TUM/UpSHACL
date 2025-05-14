from __future__ import annotations

"""High‑level helpers to load, drop, export and count graphs in Virtuoso.

All Docker calls respect ``config.DOCKER_CONTAINER_NAME`` and therefore
work no matter how you name your container (default: *new_virtuoso*).
The module contains **no heavy business logic**, only I/O with Virtuoso.
"""

from pathlib import Path
from subprocess import run, CalledProcessError
from typing import Iterable, List, Optional
import os
import time

from rdflib import Graph, URIRef
from SPARQLWrapper.SPARQLExceptions import EndPointInternalError

from src.config import (
    DOCKER_CONTAINER_NAME,
    DATA_DIR_IN_DOCKER,
    virtuoso,
    MAX_BATCH_SIZE,
)
from src.utils.sanitizer import sanitize_uri, sanitize_graph
from .graph_ops import batch  # single source of truth for batching

# ---------------------------------------------------------------------------
# Loader helper – wait until Virtuoso rdf_loader finishes
# ---------------------------------------------------------------------------

def wait_for_loader_to_finish(timeout: int = 600):
    """Poll Virtuoso's loader table until all jobs finish or timeout."""
    start = time.time()

    def _extract_loader_count(out: str) -> int:
        for line in out.splitlines():
            if "Rows" in line:
                continue
            if line.strip().isdigit():
                return int(line.strip())
        return 0

    while True:
        isql = "SELECT COUNT(*) FROM DB.DBA.load_list WHERE ll_state < 2;"
        proc = run(
            ["docker", "exec", "-i", DOCKER_CONTAINER_NAME, "isql", "-U", "dba", "-P", "dba"],
            input=isql,
            capture_output=True,
            text=True,
            check=True,
        )
        out = proc.stdout
        print("[Virtuoso] loader status:\n", out)

        cnt = _extract_loader_count(out)
        if cnt == 0:
            print("[Virtuoso] loader finished")
            return
        if time.time() - start > timeout:
            raise TimeoutError("Virtuoso loader did not finish within timeout")
        time.sleep(1)



# ---------------------------------------------------------------------------
# Graph management helpers
# ---------------------------------------------------------------------------

def delete_data(graph_uri: str):
    """DROP SILENT GRAPH with exponential back‑off on Virtuoso lock time‑outs."""

    for attempt in range(3):
        try:
            virtuoso.update(f"DROP SILENT GRAPH <{graph_uri}>")
            print(f"Dropped graph <{graph_uri}>")
            return
        except EndPointInternalError as exc:
            if attempt == 2:
                raise
            print("Virtuoso timeout – retry in 2 s…")
            time.sleep(2)


# ---------------------------------------------------------------------------
# Bulk loader using ld_dir + rdf_loader_run (kept for backwards compat)
# ---------------------------------------------------------------------------

def _isql(cmd: str):
    run(
        [
            "docker",
            "exec",
            "-i",
            DOCKER_CONTAINER_NAME,
            "isql",
            "-U",
            "dba",
            "-P",
            "dba",
        ],
        input=cmd,
        text=True,
        check=True,
    )


def clean_and_bulk_load_ttl(file_path: str | os.PathLike, graph_uri: str):
    """Clear *graph_uri* and load *file_path* via Virtuoso's batch loader."""

    file_path = Path(file_path)
    ttl_name = file_path.name

    print(f"[LOAD] clearing graph <{graph_uri}> …")
    _isql(f"SPARQL DROP SILENT GRAPH <{graph_uri}>;")

    print(f"[LOAD] cleaning stale load_list rows for {ttl_name} ...")
    _isql(f"DELETE FROM DB.DBA.load_list WHERE ll_file LIKE '%{ttl_name}%';")

    print(f"[LOAD] ld_dir + rdf_loader_run …")
    _isql(
        f"""
        ld_dir('{DATA_DIR_IN_DOCKER}', '{ttl_name}', '{graph_uri}');
        rdf_loader_run();
        """
    )


# ---------------------------------------------------------------------------
# Graph export helpers
# ---------------------------------------------------------------------------

def _stream_construct(graph_uri: str, offset: int, limit: int) -> bytes:
    q = (
        f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }} "
        f"OFFSET {offset} LIMIT {limit}"
    )
    return virtuoso.query(q)  # bytes


def export_graph_raw(graph_uri: str, out_path: str | os.PathLike, chunk: int = 50_000):
    """Stream the entire graph to *out_path* in chunks without rdflib."""

    out_path = Path(out_path)
    offset = 0
    with out_path.open("wb") as fh:
        while True:
            data = _stream_construct(graph_uri, offset, chunk)
            # Virtuoso returns an empty body (just headers) when OFFSET > size
            if not data or len(data) < 200:
                break
            fh.write(data)
            offset += chunk
            print(f"  wrote ~{offset:,} triples", end="\r")
    print(f"\n[EXPORT] complete -> {out_path}")
    return str(out_path)


# ---------------------------------------------------------------------------
# In‑memory helpers (rdflib) – only for tests / tiny graphs
# ---------------------------------------------------------------------------

def load_graph_from_file(file_path: str | os.PathLike) -> Graph:
    return Graph().parse(file_path, format="turtle")


def load_graph_from_virtuoso(graph_uri: str, *, batch_size: int = MAX_BATCH_SIZE) -> Graph:
    """Export an entire named graph into an in‑memory rdflib.Graph.

    **Warning**: on multi‑GB graphs this will use huge amounts of RAM.
    Use :func:`export_graph_raw` for big exports instead.
    """

    # quick COUNT so we can display progress
    n_triples = count_triples_in_graph(graph_uri)
    print(f"[EXPORT-MEM] exporting ~{n_triples:,} triples from <{graph_uri}> ...")

    g = Graph()
    offset = 0
    while True:
        data = _stream_construct(graph_uri, offset, batch_size)
        if not data or len(data) < 200:
            break
        # decode as UTF‑8 *without* raising (Virtuoso may send latin‑1 bytes)
        text = data.decode("utf‑8", "ignore")
        batch = Graph().parse(data=text, format="n3")
        g += sanitize_graph(batch)
        offset += batch_size
        print(f"  fetched {offset:,}", end="\r")
    print()
    return g


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def count_triples_in_graph(graph_uri: str) -> int:
    q = f"SELECT (COUNT(*) AS ?c) WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    res = virtuoso.query(q)
    return int(res["results"]["bindings"][0]["c"]["value"])


# ---------------------------------------------------------------------------
# Public main API: load_data
# ---------------------------------------------------------------------------

def load_data(data_file: str, shapes_file: str, data_graph_uri: str, shapes_graph_uri: str):
    """Clear both graphs, bulk‑load the Turtle files, wait until done."""

    print("[LOAD] loading data & shapes into Virtuoso …")
    clean_and_bulk_load_ttl(data_file, data_graph_uri)
    clean_and_bulk_load_ttl(shapes_file, shapes_graph_uri)
    wait_for_loader_to_finish()

    # sanity counts
    for g in (data_graph_uri, shapes_graph_uri):
        print(f"  {g} ->  {count_triples_in_graph(g):,} triples")

    print("[LOAD] done.")
