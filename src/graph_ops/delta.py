from __future__ import annotations

from rdflib import RDF, Node, Graph
from typing import Dict, List, Set, Tuple
import collections
import uuid

from ..config import NODE_BATCH_SIZE, virtuoso
from ..pathexpr import path_to_sparql_pattern
from ..utils.custom_types import Triple
from ..utils.sanitizer import sanitize_uri, build_sparql_triples
from ..config_dynamic import get_data_graph_uri

from .crud import batch as chunker, insert_triples
from .traversal import expand_nodes
from ..shacl_index import ShapeIndex
from src.utils.path_processor import PathProcessor

AffectedPair = Tuple[str, str]  # (nodeIRI, shapeIRI)
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
NODE_VAL_BATCH = 1_000
CLASS_VAL_BATCH = 8_000

def _as_sparql(triples: List[str] | List[Tuple]) -> str:
    if not triples:
        return ""
    if isinstance(triples[0], str):
        return " ".join(triples)
    return " ".join(build_sparql_triples(triples))

def _iri_list(items: Set[str] | List[str]) -> str:
    return " ".join(f"<{sanitize_uri(i)}>" for i in items if i.startswith("http"))

def compute_affected_pairs(delta_insert: List[str], delta_delete: List[str]) -> List[AffectedPair]:
    idx = ShapeIndex()

    delta_graph = f"http://temp.org/delta_{uuid.uuid4()}"
    virtuoso.update(f"CREATE SILENT GRAPH <{delta_graph}>")

    if delta_insert:
        virtuoso.update(f"INSERT DATA {{ GRAPH <{delta_graph}> {{ {_as_sparql(delta_insert)} }} }}")
    if delta_delete:
        virtuoso.update(f"INSERT DATA {{ GRAPH <{delta_graph}> {{ {_as_sparql(delta_delete)} }} }}")

    path_preds = {p for p in idx.path_predicates}
    path_preds.add(RDF_TYPE)

    object_preds = {p for tgt in idx.target_map.values() for p in tgt["objectsOf"]}
    obj_sensitive_map = idx.prop_to_parent_shapes
    obj_sensitive_preds = set(obj_sensitive_map.keys())
    val_sensitive_map = idx.value_sensitive_paths
    val_sensitive_preds = set(val_sensitive_map.keys())

    subject_nodes = _select_iris(delta_graph, "s", set(), is_subject=True)
    object_nodes = _select_iris(delta_graph, "o", object_preds, is_subject=False)
    initial_nodes: Set[str] = subject_nodes | object_nodes
    affected_pairs: Set[AffectedPair] = set()

    if val_sensitive_preds and object_nodes:
        node_values = _iri_list(object_nodes)
        val_hop_q = make_path_query(
            path_nodes=val_sensitive_preds,
            shapes_graph=idx.graph,
            graph_uri=get_data_graph_uri(),
            values_clause=node_values,
            source_var="?s",
            target_var="?o",
            depth=3,
        )
        val_hop_res = virtuoso.query_select(val_hop_q)
        val_subjects = {b["s"]["value"] for b in val_hop_res["results"]["bindings"]}
        initial_nodes |= val_subjects

    if obj_sensitive_preds and initial_nodes:
        node_values = _iri_list(initial_nodes)
        obj_hop_q = make_path_query(
            path_nodes=obj_sensitive_preds,
            shapes_graph=idx.graph,
            graph_uri=get_data_graph_uri(),
            values_clause=node_values,
            source_var="?s",
            target_var="?o",
            depth=3,
        )
        obj_hop_res = virtuoso.query_select(obj_hop_q)
        hop_subjects = {b["s"]["value"] for b in obj_hop_res["results"]["bindings"]}
        initial_nodes |= hop_subjects

    properties = {
        path_to_sparql_pattern(p, idx.graph)
        for p in idx.node_properties
    }
    expanded_nodes = expand_nodes(initial_nodes, properties)

    for shape, tgt in idx.target_map.items():
        affected_pairs.update(_match_shape(
            shape, tgt, expanded_nodes, subject_nodes, initial_nodes
        ))

    virtuoso.update(f"DROP SILENT GRAPH <{delta_graph}>")
    return list(affected_pairs)


def make_path_query(
    path_nodes: Set[Node],
    shapes_graph,
    graph_uri: str,
    values_clause: str,
    source_var: str = "?s",
    target_var: str = "?o",
    depth: int = 3,
) -> str:
    patterns = "\n".join(
        path_to_sparql_pattern(path_node, shapes_graph, source_var, target_var, depth)
        for path_node in path_nodes
    )


    return f"""
    SELECT DISTINCT {source_var}
    WHERE {{
      GRAPH <{graph_uri}> {{
        VALUES {target_var} {{ {values_clause} }}
        {patterns}
      }}
    }}"""

def _select_iris(delta_graph: str, var: str, predicates: Set[str], *, is_subject: bool) -> Set[str]:
    pattern = f"?{var} ?p ?o" if is_subject else f"?s ?p ?{var}"
    pred_clause = f"FILTER (?p IN ({', '.join(f'<{sanitize_uri(p)}>' for p in predicates)}))" if predicates else ""
    q = f"""
    SELECT DISTINCT ?{var}
    WHERE {{
      GRAPH <{delta_graph}> {{
        {pattern} .
        FILTER isIRI(?{var})
        {pred_clause}
      }}
    }}"""
    res = virtuoso.query_select(q)
    return {b[var]["value"] for b in res["results"]["bindings"]}

def match_nodes_via_predicate(predicate_set: Set[str], var: str, check_nodes: Set[str], compare_nodes: Set[str], shape: str) -> Set[AffectedPair]:
    if not predicate_set:
        return set()
    pred_filter = f"FILTER (?p IN ({', '.join(f'<{sanitize_uri(p)}>' for p in predicate_set)}))"
    target = "?s" if var == "s" else "?o"
    q = f"""
    SELECT DISTINCT {target}
    WHERE {{
      GRAPH <{get_data_graph_uri()}> {{
        ?s ?p ?o .
        {pred_filter}
      }}
    }}"""
    bindings = virtuoso.query_select(q)["results"]["bindings"]
    found = {b[target[1:]]["value"] for b in bindings}
    return {(n, shape) for n in check_nodes if n in found and n in compare_nodes}

def match_class_instances(classes: Set[str], nodes: Set[str], initial_nodes: Set[str], shape: str) -> Set[AffectedPair]:
    if not classes or not nodes:
        return set()
    matches = set()
    for cls_slice in chunker(list(classes), CLASS_VAL_BATCH):
        class_values = _iri_list(cls_slice)
        for node_slice in chunker(list(nodes), NODE_VAL_BATCH):
            node_values = _iri_list([n for n in node_slice if n.startswith("http")])
            if not node_values:
                continue
            q = f"""
            SELECT DISTINCT ?inst
            WHERE {{
              GRAPH <{get_data_graph_uri()}> {{
                VALUES ?inst {{ {node_values} }}
                VALUES ?cls  {{ {class_values} }}
                ?inst a ?cls .
              }}
            }}"""
            bindings = virtuoso.query_select(q)["results"]["bindings"]
            for b in bindings:
                inst = b["inst"]["value"]
                if inst in initial_nodes:
                    matches.add((inst, shape))
    return matches

def flatten_pairs(batch_pairs: List[AffectedPair], allowed_map: Dict[str, Set[str]]) -> Tuple[Set[str], Set[str]]:
    """Extract nodes and patterns from affected pairs.
    
    Args:
        batch_pairs: List of (node, shape) tuples
        allowed_map: Dict mapping shape URI to set of SPARQL patterns
    
    Returns:
        Tuple of (set of node URIs, set of SPARQL patterns)
    """
    nodes = {n for n, _ in batch_pairs}
    patterns = {p for _, shape in batch_pairs for p in allowed_map.get(shape, set())}
    return nodes, patterns

def _match_shape(shape: str, targets: Dict[str, Set[str]], expanded_nodes: Set[str], core_subject_nodes: Set[str], initial_nodes: Set[str]) -> Set[AffectedPair]:
    matches: Set[AffectedPair] = set()
    shape_str = str(shape)
    matches |= {(n, shape_str) for n in expanded_nodes if n in targets["nodes"]}
    matches |= match_class_instances(targets["classes"], expanded_nodes, initial_nodes, shape_str)
    matches |= match_nodes_via_predicate(targets["subjectsOf"], "s", expanded_nodes, initial_nodes, shape_str)
    matches |= match_nodes_via_predicate(targets["objectsOf"], "o", expanded_nodes, initial_nodes, shape_str)
    return matches


def build_reduced_graphs(affected_pairs: List[AffectedPair]) -> Tuple[str, List[(Node, Node, Node)]]:
    idx = ShapeIndex()
    temp_graph = f"http://temp.org/data_{uuid.uuid4()}"
    virtuoso.update(f"CREATE SILENT GRAPH <{temp_graph}>")

    if not affected_pairs:
        print("[delta] no affected pairs -> empty reduced graph")
        return temp_graph, []

    allowed_props_map = idx.shape_triple_patterns
    print(allowed_props_map)
    visited: Set[AffectedPair] = set()
    queue = collections.deque(affected_pairs)
    inserted_total = 0
    inserted_triples: List[(Node, Node, Node)] = []

    while queue:
        batch_pairs = _collect_batch(queue, visited)
        start_nodes, patterns = flatten_pairs(batch_pairs, allowed_props_map)
        print("  >> batch nodes:", start_nodes)
        print("  >> allowed patterns:", patterns)

        triples = traverse_all(start_nodes=start_nodes, patterns=patterns)

        print(f"[fetch] got {len(triples)} triples")
        inserted_triples.extend(triples)
        insert_triples(temp_graph, triples)
        inserted_total += len(triples)

    print(f"[delta] reduced graph <{temp_graph}> <- {inserted_total} triples")
    return temp_graph, inserted_triples


def traverse_all(start_nodes: Set[str], patterns: Set[str], depth: int = 3) -> List[(Node, Node, Node)]:
    if not start_nodes or not patterns:
        return []

    all_triples = []
    nodes_clause = _iri_list(start_nodes)
    data_graph = get_data_graph_uri()

    for pattern in patterns:
        query = f"""
            CONSTRUCT {{
              {pattern}
            }}
            WHERE {{
              GRAPH <{data_graph}> {{
                VALUES ?s {{ {nodes_clause} }}
                {pattern}
              }}
            }}
        """
        result = virtuoso.query(query)
        print(result)
        g = Graph()
        g.parse(data=result.decode("utf-8"), format="turtle")
        for s, p, o in g:
            all_triples.append((s, p, o))
        # for b in bindings:
        #     print(b)
        #     all_triples.append((b["s"]["value"], b["p"]["value"], b["o"]["value"]))

    return all_triples

def _collect_batch(queue: collections.deque, visited: Set[AffectedPair]) -> List[AffectedPair]:
    batch: List[AffectedPair] = []
    while queue and len(batch) < NODE_BATCH_SIZE:
        pair = queue.popleft()
        if pair not in visited:
            visited.add(pair)
            batch.append(pair)
    return batch
