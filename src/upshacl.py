import uuid
from rdflib import Graph

from src.data_loader import load_data, delete_data, export_graph_raw
from src.config_dynamic import set_graph_uris, get_data_graph_uri
from src.graph_ops import compute_affected_pairs, build_reduced_graphs, insert_triples, delete_triples, cleanup_temp_graphs
from src.shacl_index import ShapeIndex
from src.store import virtuoso
from src.utils.sanitizer import build_sparql_triples, build_sparql_triples_nodes
from src.utils.utils import to_internal_triples


def run_UpSHACL(
    data_file: str,
    shapes_file: str,
    insert_file: str,
    delete_file: str,
    output_reduced_file: str,
    *,
    verbose: bool = False,
    cleanup: bool = True,
):
    """
    Run the UpSHACL graph reduction pipeline.

    Args:
        data_file: Path to the full input data graph (Turtle).
        shapes_file: Path to the SHACL shapes graph (Turtle).
        insert_file: Path to Turtle file with inserted triples.
        delete_file: Path to Turtle file with deleted triples.
        output_reduced_file: Path to write the reduced data graph (Turtle).
        verbose: If True, print progress messages.
        cleanup: If True, remove temporary Virtuoso graphs after execution.
    """

    # ───── Setup temp named graphs ─────
    uid = str(uuid.uuid4())[:8]
    data_uri = f"http://example.org/graph/entrypoint/{uid}"
    shapes_uri = f"http://example.org/shapes/entrypoint/{uid}"
    set_graph_uris(data_uri, shapes_uri)

    if verbose:
        print("Loading data and shapes into Virtuoso...")
    load_data(data_file, shapes_file, data_uri, shapes_uri)

    # ───── Load inserted/deleted triples (assume Turtle) ─────
    def load_triples(file_path: str):
        g = Graph().parse(file_path, format="turtle")
        return list(g)

    # inserted = to_internal_triples(load_triples(insert_file))
    # deleted = to_internal_triples(load_triples(delete_file))
    inserted = load_triples(insert_file)
    deleted = load_triples(delete_file)


    # ───── Apply deltas to Virtuoso ─────
    if verbose:
        print(f"Applying {len(deleted)} deletions...")
    delete_triples(data_uri, deleted)

    if verbose:
        print(f"Applying {len(inserted)} insertions...")
    insert_triples(data_uri, inserted)

    # Load SHACL shapes file into rdflib graph
    shapes_graph = Graph().parse(shapes_file, format="turtle")

    # Override ShapeIndex to use rdflib instead of Virtuoso
    ShapeIndex.override_with_graph(shapes_graph)
    # ───── Compute affected node-shape pairs ─────
    if verbose:
        print("Computing affected node-shape pairs...")
    affected_pairs = compute_affected_pairs(
                        build_sparql_triples_nodes(inserted),
                        build_sparql_triples_nodes(deleted)
                    )

    # ───── Build and export reduced graph ─────
    if verbose:
        print("Building reduced data graph...")

    G_red_uri, _ = build_reduced_graphs(affected_pairs)

    export_graph_raw(G_red_uri, output_reduced_file)
    if verbose:
        print(f"Reduced graph written to: {output_reduced_file}")

    # ───── Optional cleanup ─────
    if cleanup:
        if verbose:
            print("Cleaning up temporary graphs...")
        delete_data(data_uri)
        delete_data(shapes_uri)
        cleanup_temp_graphs()

    if verbose:
        print("UpSHACL pipeline complete.")
