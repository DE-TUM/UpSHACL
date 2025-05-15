from __future__ import annotations

"""Benchmark runner for the incremental‑validation pipeline.

One *experiment* consists of:
  1. bulk‑loading a fresh data + shapes graph into Virtuoso
  2. exporting an initial full‑graph (FG₀) SHACL report
  3. repeating *N* batches of mixed deletions & insertions
     → after each batch we call ``run_incremental_pipeline``

The script can run a **slice** of the global *experiments* list, so you
can launch slices in parallel (e.g. with GNU Parallel or a job queue).
"""

import os
import sys
import traceback
import uuid
from datetime import datetime
from itertools import islice
from typing import List

from src.config import STORAGE_DIR
from ..utils.utils import make_validation_report_path, save_delta_batch_as_ttl

# project‑local helpers ------------------------------------------------------
from ..config_dynamic import (
    set_graph_uris,
    get_data_graph_uri,
    get_shapes_graph_uri,
)
from ..data_loader import load_data, delete_data

# CRUD helpers now live in *graph_ops*
from ..graph_ops import (
    sample_triples_from_graph,
    delete_triples,
    insert_triples,
)

from .validation import (
    run_incremental_pipeline,
    export_full_validation_report_from_virtuoso, export_fg0_from_file_with_removals,
)
import logging

# Suppress rdflib.term URI warnings
logging.getLogger("rdflib.term").setLevel(logging.ERROR)

# ────────────────────────────────────────────────────────────────────────────
# helper: add STORAGE_DIR prefix only when STORAGE_DIR is set
# ────────────────────────────────────────────────────────────────────────────

def _add_prefix(path: str) -> str:  # noqa: D401 (helper)
    return os.path.join(STORAGE_DIR, path) if STORAGE_DIR else path


# ────────────────────────────────────────────────────────────────────────────
#  experiments list  (file, shapes, csv)
# ────────────────────────────────────────────────────────────────────────────

experiments: List[tuple[str, str, str]] = [
    ("data/EnDe-Lite50(without_Ontology).ttl", "data/shape30_clean.ttl", "results/EnDe50.csv"),
    ("data/EnDe-Lite100(without_Ontology).ttl", "data/shape30_clean.ttl", "results/EnDe100.csv"),
    ("data/EnDe-Lite1000(without_Ontology).ttl", "data/shape30_clean.ttl", "results/EnDe1000.csv"),
    ("data/lubm-skg-1.ttl", "data/schema1.ttl", "results/skg1_schema1.csv"),
    ("data/lubm-mkg-1.ttl", "data/schema1.ttl", "results/mkg1_schema1.csv"),
    ("data/lubm-lkg-1.ttl", "data/schema1.ttl", "results/lkg1_schema1.csv"),
    ("data/lubm-skg-1.ttl", "data/schema2.ttl", "results/skg1_schema2.csv"),
    ("data/lubm-mkg-1.ttl", "data/schema2.ttl", "results/mkg1_schema2.csv"),
    ("data/lubm-lkg-1.ttl", "data/schema2.ttl", "results/lkg1_schema2.csv"),
    ("data/lubm-skg-1.ttl", "data/schema3.ttl", "results/skg1_schema3.csv"),
    ("data/lubm-mkg-1.ttl", "data/schema3.ttl", "results/mkg1_schema3.csv"),
    ("data/lubm-lkg-1.ttl", "data/schema3.ttl", "results/lkg1_schema3.csv"),
]

# # --- TEMP: run only one experiment while debugging -------------------------
# experiments = [
#     ("data/EnDe-Lite50(without_Ontology).ttl", "data/shape30_clean.ttl", "results/EnDe50.csv"),
# ]

# result paths --------------------------------------------------------------
master_log_file = "results/master_results.csv"
log_output_file = "results/full_log.txt"


# ───────────────────────────────────────────────────────────────────────────
# helpers
# ────────────────────────────────────────────────────────────────────────────

def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _stream_slices(iterable, size):
    """Yield *lists* of length ≤ *size* from *iterable* without buffering all."""
    it = iter(iterable)
    while chunk := list(islice(it, size)):
        yield chunk


# ────────────────────────────────────────────────────────────────────────────
# core routine for one experiment
# ────────────────────────────────────────────────────────────────────────────

def benchmark_incremental_mixed(
    data_file: str,
    shapes_file: str,
    csv_file: str,
    *,
    total_size: int = 3_000,
    batch_size: int = 1_000,
):
    """Load graphs, run *mixed* insert/delete batches from .ttl files, write CSV & reports."""

    # absolute / prefixed paths --------------------------------------------
    data_file = _add_prefix(data_file)
    shapes_file = _add_prefix(shapes_file)
    csv_file = _add_prefix(csv_file)

    print(f"Benchmarking {total_size} triples in batches of {batch_size}")

    if total_size % batch_size:
        raise ValueError("total_size must be divisible by batch_size")
    num_batches = total_size // batch_size

    # 1) initial bulk‑load ---------------------------------------------------
    load_data(data_file, shapes_file, get_data_graph_uri(), get_shapes_graph_uri())

    # 2) load deltas from .ttl files -----------------------------------------
    from .delta_cache import DeltaCache

    # Construct base_name used in filenames (e.g. EnDe-Lite50without_Ontology__shape30_clean)
    base_name = os.path.basename(data_file).replace(".ttl", "").replace("(", "").replace(")", "") + "__" + \
                os.path.basename(shapes_file).replace(".ttl", "")

    DeltaCache.load_from_files(base_name=base_name, num_batches=num_batches)

    # Clear inserted triples from Virtuoso to simulate starting point
    inserted, _ = DeltaCache.get_all()
    delete_triples(get_data_graph_uri(), inserted)

    # 3) process batches -----------------------------------------------------
    for i in range(num_batches):
        ins_chunk, del_chunk = DeltaCache.get_batch(batch_size, i)

        print(f"\nStep {i + 1}/{num_batches}: applying {batch_size} insertions & deletions")
        insert_triples(get_data_graph_uri(), ins_chunk)
        delete_triples(get_data_graph_uri(), del_chunk)

        run_incremental_pipeline(
            data_file=data_file,
            shapes_file=shapes_file,
            csv_file=csv_file,
            batch_index=i,
            batch_size=batch_size
        )

    print(f"\nBenchmark complete -> {csv_file}")


# ────────────────────────────────────────────────────────────────────────────
# experiment slicing wrapper
# ────────────────────────────────────────────────────────────────────────────

def _generate_graph_uris(experiment_name: str):
    uid = str(uuid.uuid4())[:8]
    return (
        f"http://example.org/graph/{experiment_name}/{uid}",
        f"http://example.org/shapes/{experiment_name}/{uid}",
    )


def run_all_experiments(slice_id: int = 0, num_slices: int = 1):
    os.makedirs("results", exist_ok=True)

    total = len(experiments)
    chunk = (total + num_slices - 1) // num_slices
    subset = experiments[slice_id * chunk : min((slice_id + 1) * chunk, total)]

    with open(log_output_file, "a", encoding="utf-8") as log_f:

        def log(msg: str):
            line = f"[{_timestamp()}] {msg}"
            print(line)
            log_f.write(line + "\n")
            log_f.flush()

        for idx, (data_file, shapes_file, out_csv) in enumerate(subset, 1):
            log(f"Experiment {idx}/{len(subset)}: {data_file} + {shapes_file}")

            # isolate graphs per experiment
            set_graph_uris(*_generate_graph_uris(os.path.basename(out_csv).removesuffix(".csv")))

            try:
                benchmark_incremental_mixed(data_file, shapes_file, out_csv)
                log("Success")
            except Exception as exc:
                log(f"Failed: {exc}\n{traceback.format_exc()}")
            finally:
                # clean‑up graphs in Virtuoso
                delete_data(get_data_graph_uri())
                delete_data(get_shapes_graph_uri())

    print("ALL DONE")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry‑point
# ────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        run_all_experiments(int(sys.argv[1]), int(sys.argv[2]))
    else:
        run_all_experiments()
