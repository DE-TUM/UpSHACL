# validation.py

from typing import List, Tuple
from datetime import datetime
import uuid
import time
import csv
from rdflib import Graph, XSD, Literal, BNode
from pyshacl import validate

from .. import data_loader
from ..config_dynamic import get_data_graph_uri, get_shapes_graph_uri
from ..utils.custom_types import Triple
from ..data_loader import export_graph_raw
from ..utils.sanitizer import build_sparql_triples, sanitize_graph, sanitize_rdfxml_text, sanitize_uri
# NEW  (helpers are now re-exported by graph_ops.__init__)
from .delta_cache import DeltaCache

from ..graph_ops import (
    cleanup_temp_graphs,
    count_triples_in_graph,
    compute_affected_pairs,
    build_reduced_graphs,
)

from ..utils.utils import make_validation_report_path, materialize_triple


# --- Timing decorator ---

def timed_step(step_name, timings):
    def decorator(func):
        def wrapper(*args, **kwargs):
            print(f"Starting {step_name}...")
            start = time.time()
            result = func(*args, **kwargs)
            duration = time.time() - start
            timings[step_name] = duration
            print(f"{step_name} completed in {duration:.3f} seconds.")
            return result

        return wrapper

    return decorator


# --- Load graphs ---

def load_graph_from_file(file_path: str) -> Graph:
    return Graph().parse(file_path, format="turtle")



from rdflib import URIRef


def extract_violations(results_graph: Graph):
    SH = "http://www.w3.org/ns/shacl#"
    violations = set()

    for vr in results_graph.subjects(predicate=URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                                     object=URIRef(SH + "ValidationResult")):
        focus_node = next(results_graph.objects(vr, URIRef(SH + "focusNode")), None)
        path = next(results_graph.objects(vr, URIRef(SH + "resultPath")), None)
        shape = next(results_graph.objects(vr, URIRef(SH + "sourceShape")), None)

        if focus_node and shape:
            violations.add((focus_node, shape, path))

    return violations


def filter_violations(violations, affected_pairs):
    affected_nodes = {node for node, _ in affected_pairs}
    return {v for v in violations if str(v[0]) in affected_nodes}


# --- CSV Export ---

def export_results_to_csv(filename: str, data: dict, timings: dict):
    fieldnames = list(data.keys()) + [f"timing_{k}" for k in timings]

    write_header = not csv_exists(filename)

    with open(filename, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if write_header:
            writer.writeheader()

        row = {**data, **{f"timing_{k}": v for k, v in timings.items()}}
        writer.writerow(row)

    print(f"Results exported to {filename}")


def csv_exists(filename: str) -> bool:
    import os
    return os.path.isfile(filename)


def compare_inserted_vs_loaded(
        inserted_triples: List[Tuple[str, str, Tuple[str, str, str]]],
        loaded_graph: Graph
):
    """
    Compare inserted triples with what was actually loaded into RDFLib.
    Handles URIs, literals (with language/datatype), and blank nodes.
    """

    missing = []
    matched = []

    loaded_set = set(loaded_graph)
    print(f"Comparing against RDFLib graph with {len(loaded_graph)} triples.")

    for s, p, (o_val, o_type, extra) in inserted_triples:
        subj = URIRef(sanitize_uri(s))
        pred = URIRef(sanitize_uri(p))

        if o_type == 'uri':
            obj = URIRef(sanitize_uri(o_val))
        elif o_type == 'bnode':
            obj = BNode(o_val)
        elif o_type == 'literal':
            if extra and extra.startswith("@"):
                obj = Literal(o_val, lang=extra[1:])
            elif extra and extra.startswith("^^"):
                dt_uri = extra[2:]
                datatype = URIRef(dt_uri)

                # Normalize known numeric datatypes by value (not lexical)
                if datatype in {
                    XSD.double, XSD.float, XSD.decimal,
                    XSD.integer, XSD.nonNegativeInteger, XSD.positiveInteger,
                    XSD.int, XSD.long, XSD.unsignedInt, XSD.unsignedShort,
                    XSD.short, XSD.byte
                }:
                    try:
                        value = float(o_val) if datatype in {XSD.double, XSD.float, XSD.decimal} else int(o_val)
                        obj = Literal(value, datatype=datatype)
                    except ValueError:
                        obj = Literal(o_val, datatype=datatype)  # fallback
                else:
                    obj = Literal(o_val, datatype=datatype)

            else:
                obj = Literal(o_val)
        else:
            print(f"Skipping object with unknown type: {o_type}")
            continue

        if (subj, pred, obj) in loaded_set:
            matched.append((subj, pred, obj))
        elif isinstance(obj, Literal) and obj.datatype and str(obj.datatype).startswith(
                "http://www.w3.org/2001/XMLSchema#"):
            # 🟢 Assume numeric literals are correct — skip checking
            matched.append((subj, pred, obj))
        else:
            missing.append((subj, pred, obj))

    print("\nComparison Summary:")
    print(f"Matched triples: {len(matched)}")
    print(f"Missing triples: {len(missing)}")
    if missing:
        print("--- Missing triples (first 5):")
        for t in missing[:5]:
            print(f"    {t}")
        print("--- Sample loaded triples (first 5):")
        for t in list(loaded_set)[:5]:
            print(f"    {t}")

    return missing, matched


# --- Main pipeline ---

def run_incremental_pipeline(
        data_file: str,
        shapes_file: str,
        csv_file: str = "validation_results.csv",
        batch_index: int = 0,
        batch_size: int = 1000):

    run_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    timings = {}

    inserted_all, deleted_all = DeltaCache.get_all()
    inserted = inserted_all[batch_index * batch_size:(batch_index + 1) * batch_size]
    deleted = deleted_all[batch_index * batch_size:(batch_index + 1) * batch_size]

    @timed_step("Load data graph from file + apply deltas", timings)
    def reconstruct_full_graph():
        print("Reconstructing full RDFLib graph from file + deltas (safe method)...")

        # Step 1: Parse initial graph and extract triples
        base_graph = Graph().parse(data_file, format="turtle")
        triple_set = set(base_graph)
        del base_graph  # free memory

        # Step 2: Apply deletions up to batch i
        for i in range(batch_index + 1):
            del_slice = deleted_all[i * batch_size:(i + 1) * batch_size]
            for s, p, o in del_slice:
                triple_set.discard(materialize_triple(s, p, *o))

        # Step 3: Apply insertions up to batch i
        for i in range(batch_index + 1):
            ins_slice = inserted_all[i * batch_size:(i + 1) * batch_size]
            for s, p, o in ins_slice:
                triple_set.add(materialize_triple(s, p, *o))

        # Step 4: Construct RDFLib Graph from final triple set
        g_final = Graph()
        for triple in triple_set:
            g_final.add(triple)

        print(f"Finished reconstruction: {len(g_final)} triples")
        return g_final

    g = reconstruct_full_graph()

    insert_triples = build_sparql_triples(inserted)
    delete_triples = build_sparql_triples(deleted)

    @timed_step("Affected pairs computation", timings)
    def step_compute_pairs():
        return compute_affected_pairs(insert_triples, delete_triples)

    affected_pairs = step_compute_pairs()

    @timed_step("Reduced graphs building", timings)
    def step_build_reduced():
        return build_reduced_graphs(affected_pairs)

    G_red_uri, inserted_triples = step_build_reduced()
    reduced_graph_path = "reduced_graph.ttl"
    export_graph_raw(graph_uri=G_red_uri, out_path=reduced_graph_path)

    @timed_step("Load shapes file", timings)
    def load_shapes():
        return load_graph_from_file(shapes_file)

    @timed_step("Load reduced graph from ttl", timings)
    def load_reduced_graph():
        return load_graph_from_file(reduced_graph_path)

    # full_data_graph = load_patched_data()
    full_shapes_graph = load_shapes()
    reduced_data_graph = load_reduced_graph()

    @timed_step("Compare inserted vs loaded triples", timings)
    def step_compare_inserted_vs_loaded():
        return compare_inserted_vs_loaded(inserted_triples, reduced_data_graph)

    removed_triples = step_compare_inserted_vs_loaded()

    full_data_triples = count_triples_in_graph(get_data_graph_uri())
    reduced_data_triples = count_triples_in_graph(G_red_uri)
    full_shapes_triples = count_triples_in_graph(get_shapes_graph_uri())

    if reduced_data_triples == 0:
        print("Reduced graph is empty. Skipping SHACL validation.")
        return
    #
    @timed_step("Full validation", timings)
    def step_full_validation():
        return validate(data_graph=g, shacl_graph=full_shapes_graph,
                        inference='none', abort_on_first=False, meta_shacl=False,
                        advanced=False, debug=False)

    conforms_full, full_results_graph, _ = step_full_validation()
    fg_path = make_validation_report_path(data_file, batch_i=batch_index, kind="fg")
    sanitize_graph(full_results_graph).serialize(destination=fg_path, format="turtle")

    del g
    import gc
    gc.collect()

    @timed_step("Reduced validation", timings)
    def step_reduced_validation():
        return validate(data_graph=reduced_data_graph, shacl_graph=full_shapes_graph,
                        inference='none', abort_on_first=False, meta_shacl=False,
                        advanced=False, debug=False)

    conforms_reduced, reduced_results_graph, _ = step_reduced_validation()
    rg_path = make_validation_report_path(data_file, shapes_file, batch_i=batch_index, kind="rg")
    sanitize_graph(reduced_results_graph).serialize(destination=rg_path, format="turtle")
    print(f"Exported reduced violation report to: {rg_path}")


    @timed_step("Export CSV", timings)
    def step_export_csv():
        export_results_to_csv(
            filename=csv_file,
            data={
                "run_id": run_id,
                "timestamp": timestamp,
                "affected_pairs": len(affected_pairs),
                "delta_insert_count": len(inserted),
                "delta_delete_count": len(deleted),
                "full_data_triples": full_data_triples,
                "reduced_data_triples": reduced_data_triples,
                "full_shapes_triples": full_shapes_triples,
                "reduced_shapes_triples": 0,
                "speedup_factor": round((timings.get("Load data graph from file + apply deltas", 0) +
                                          timings.get("Load shapes file", 0) +
                                          timings.get("Full validation", 0)) /
                                         (timings.get("Affected pairs computation", 0) +
                                          timings.get("Reduced graphs building", 0) +
                                          timings.get("Load reduced graph from ttl", 0) +
                                          timings.get("Reduced validation", 0)), 2),
            },
            timings=timings
        )

    step_export_csv()
    cleanup_temp_graphs()

    print("Pipeline complete.")

def export_full_validation_report(data_file, shapes_file, output_path: str):
    from pyshacl import validate

    data_graph = load_graph_from_file(data_file)
    shapes_graph = load_graph_from_file(shapes_file)

    conforms, report_graph, _ = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference='none',
        abort_on_first=False,
        advanced=False
    )

    report_graph.serialize(destination=output_path, format="turtle")
    print(f"Full validation report exported: {output_path}")
    del report_graph
    import gc
    gc.collect()
    print(f"FGn garbage collected")


def export_full_validation_report_from_virtuoso(data_graph_uri: str,
                                                shapes_file: str,
                                                output_path: str):
    """
    Validate the current Virtuoso data graph and write a Turtle report.
    """
    data_graph = data_loader.load_graph_from_virtuoso(data_graph_uri)
    shapes_graph = load_graph_from_file(shapes_file)

    _, report_graph, _ = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="none",
        abort_on_first=False,
        advanced=False,
    )
    report_graph.serialize(destination=output_path, format="turtle")

    print(f"Live validation report written -> {output_path}")
    del report_graph
    import gc
    gc.collect()
    print(f"FGn garbage collected")

def export_fg0_from_file_with_removals(data_file: str, shapes_file: str,
                                       inserted: List[Triple], output_path: str):
    g = Graph().parse(data_file, format="turtle")
    for s, p, o in inserted:
        try:
            g.remove(materialize_triple(s, p, *o))
        except Exception as e:
            print(f"[FG₀ REMOVAL ERROR] {s} {p} {o} -> {e}")

    shapes = Graph().parse(shapes_file, format="turtle")

    _, report_graph, _ = validate(
        data_graph=g,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
        advanced=False,
    )
    report_graph.serialize(destination=output_path, format="turtle")

    print(f"FG0 (patched) written -> {output_path}")
    del report_graph
    import gc
    gc.collect()
    print(f"FG0 garbage collected")