from __future__ import annotations

"""High-level delta processing – compute affected (node, shape) pairs and
build the reduced data sub-graph.

Public API
==========

compute_affected_pairs(delta_insert, delta_delete)
    → list[(focusNodeIRI, shapeIRI)]

build_reduced_graphs(affected_pairs)
    → (temp_data_graph_uri, list_of_inserted_triples)
"""

from typing import Dict, List, Set, Tuple
import collections
import uuid

from typing import List, Set, Tuple, Dict, Optional, Union
from ..config import NODE_BATCH_SIZE, virtuoso
from ..utils.custom_types import Triple
from ..utils.sanitizer import sanitize_uri
from ..config_dynamic import get_data_graph_uri

from .crud import batch as chunker, insert_triples
from .traversal import expand_nodes
from ..shacl_index import ShapeIndex

PathExpr = Union[str, Tuple[str, Union[str, Tuple, None], Union[str, Tuple, None]]]
# ---------------------------------------------------------------------------

AffectedPair = Tuple[str, str]            # (nodeIRI, shapeIRI)
PRED_BATCH_SIZE = 200                     # VALUES ?p chunk size
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
from ..utils.sanitizer import build_sparql_triples   # already imported elsewhere

def _as_sparql(triples: List[str] | List[Tuple]) -> str:
    """
    Return a space-separated string of N-Triples.
    Accepts either pre-formatted strings **or** structured Triple tuples.
    """
    if not triples:
        return ""
    if isinstance(triples[0], str):
        return " ".join(triples)
    # tuple case – use the existing helper
    return " ".join(build_sparql_triples(triples))


def _iri_list(items: Set[str] | List[str]) -> str:
    """Return “<iri1> <iri2> …” with guaranteed safe IRIs (no commas)."""
    return " ".join(f"<{sanitize_uri(i)}>" for i in items if i.startswith("http"))


def _select_iris(delta_graph: str, var: str, predicates: Set[str], *, is_subject: bool) -> Set[str]:
    """Pick out distinct IRIs from *delta_graph* that sit in subject/object
    position for one of *predicates*.
    """
    if not predicates:
        return set()

    in_clause = ", ".join(f"<{p}>" for p in predicates)
    pattern   = f"?{var} ?p ?o" if is_subject else f"?s ?p ?{var}"

    q = f"""
    SELECT DISTINCT ?{var}
    WHERE {{
      GRAPH <{delta_graph}> {{
        {pattern} .
        FILTER isIRI(?{var})
        FILTER (?p IN ({in_clause}))
      }}
    }}"""
    res = virtuoso.query_select(q)
    return {b[var]["value"] for b in res["results"]["bindings"]}

# ---------------------------------------------------------------------------
# 1. Affected-pair discovery
# ---------------------------------------------------------------------------


def compute_affected_pairs(delta_insert: List[str], delta_delete: List[str]) -> List[AffectedPair]:
    """Identify every (focusNode, shape) that *might* change because of the delta."""

    idx = ShapeIndex()  # singleton – cached schema look-ups

    delta_graph = f"http://temp.org/delta_{uuid.uuid4()}"
    virtuoso.update(f"CREATE SILENT GRAPH <{delta_graph}>")

    if delta_insert:
        virtuoso.update(f"""
            INSERT DATA {{ GRAPH <{delta_graph}> {{ {_as_sparql(delta_insert)} }} }}
        """)

    if delta_delete:
        virtuoso.update(f"""
            INSERT DATA {{ GRAPH <{delta_graph}> {{ {_as_sparql(delta_delete)} }} }}
        """)

    # --- predicate sets ----------------------------------------------------
    path_preds = set(idx.path_predicates)
    path_preds.add(RDF_TYPE)

    object_preds = {p for tgt in idx.target_map.values() for p in tgt["objectsOf"]}

    obj_sensitive_map = idx.prop_to_parent_shapes        # structural flattening
    obj_sensitive_preds = set(obj_sensitive_map)

    val_sensitive_map = idx.value_sensitive_paths        # semantic one-hop logic
    val_sensitive_preds = set(val_sensitive_map)

    print(f"[delta] path_preds={len(path_preds)}  targetObjectsOf={len(object_preds)}  "
          f"objSensitive={len(obj_sensitive_preds)}  valSensitive={len(val_sensitive_preds)}")

    # --- 1. IRIs directly mentioned in the delta --------------------------
    subject_nodes = _select_iris(delta_graph, "s", path_preds, is_subject=True)
    object_nodes = _select_iris(delta_graph, "o", object_preds, is_subject=False)

    initial_nodes: Set[str] = subject_nodes | object_nodes
    affected_pairs: Set[AffectedPair] = set()

    # --- 1½. one-hop backlinks from value-sensitive predicates ------------
    if val_sensitive_preds and object_nodes:
        node_values = _iri_list(object_nodes)
        pred_values = ", ".join(f"<{p}>" for p in val_sensitive_preds)

        val_hop_q = f"""
        SELECT DISTINCT ?s
        WHERE {{
          GRAPH <{get_data_graph_uri()}> {{
            VALUES ?o {{ {node_values} }}
            ?s ?p ?o .
            FILTER (?p IN ({pred_values}))
          }}
        }}
        """
        val_hop_res = virtuoso.query_select(val_hop_q)

        val_subjects = {b["s"]["value"] for b in val_hop_res["results"]["bindings"]}
        initial_nodes |= val_subjects
        print(f"[delta] value-sensitive subjects={len(val_subjects)}  total_nodes={len(initial_nodes)}")

    # --- 1¾. one-hop backlinks from obj-sensitive structural predicates ---
    if obj_sensitive_preds and initial_nodes:
        node_values = _iri_list(initial_nodes)
        pred_values = ", ".join(f"<{p}>" for p in obj_sensitive_preds)

        obj_hop_q = f"""
        SELECT DISTINCT ?s
        WHERE {{
          GRAPH <{get_data_graph_uri()}> {{
            VALUES ?o {{ {node_values} }}
            ?s ?p ?o .
            FILTER (?p IN ({pred_values}))
          }}
        }}"""
        obj_hop_res = virtuoso.query_select(obj_hop_q)

        hop_subjects = {b["s"]["value"] for b in obj_hop_res["results"]["bindings"]}
        initial_nodes |= hop_subjects
        print(f"[delta] obj-sensitive subjects={len(hop_subjects)}  nodes_total={len(initial_nodes)}")

    # --- 2. sh:node recursive expansion ------------------------------------
    expanded_nodes = expand_nodes(initial_nodes, idx.node_properties)

    # --- 3+4. match expanded nodes to each shape’s targets -----------------
    for shape, tgt in idx.target_map.items():
        affected_pairs.update(_match_shape(
            shape, tgt, expanded_nodes, subject_nodes, initial_nodes
        ))

    virtuoso.update(f"DROP SILENT GRAPH <{delta_graph}>")
    print(f"[delta] affected_pairs = {len(affected_pairs)}")
    return list(affected_pairs)

# ---------------------------------------------------------------------------
# target-matching helpers
# ---------------------------------------------------------------------------


# put near the other batching constants, e.g. right below PRED_BATCH_SIZE
NODE_VAL_BATCH = 1_000          # max IRIs per VALUES list – well below Virtuoso 10 k limit
CLASS_VAL_BATCH = 8_000

def _match_shape(
    shape: str,
    targets: Dict[str, Set[str]],
    expanded_nodes: Set[str],
    core_subject_nodes: Set[str],
    initial_nodes: Set[str],
) -> Set[AffectedPair]:
    """Return all (node, shape) pairs that *might* be validated by *shape*."""
    matches: Set[AffectedPair] = set()

    # ── 1. sh:targetNode ───────────────────────────────────────────────
    matches |= {(n, shape) for n in expanded_nodes if n in targets["nodes"]}

    # ── 2. sh:targetClass ─────────────────────────────────────────────
    if targets["classes"] and expanded_nodes:

        for cls_slice in chunker(list(targets["classes"]), CLASS_VAL_BATCH):
            class_values = _iri_list(cls_slice)

            for node_slice in chunker(list(expanded_nodes), NODE_VAL_BATCH):
                node_values = _iri_list([n for n in node_slice if n.startswith("http")])
                if not node_values:
                    continue  # slice had only bnodes

                q = f"""
                SELECT DISTINCT ?inst
                WHERE {{
                  GRAPH <{get_data_graph_uri()}> {{
                    VALUES ?inst {{ {node_values} }}
                    VALUES ?cls  {{ {class_values} }}
                    ?inst a ?cls .
                  }}
                }}"""

                res = virtuoso.query_select(q)
                for b in res["results"]["bindings"]:
                    inst = b["inst"]["value"]
                    if inst in core_subject_nodes:  # optional stricter filter
                        matches.add((inst, shape))

    # ── 3. sh:targetSubjectsOf ─────────────────────────────────────────
    if targets["subjectsOf"]:
        props = ", ".join(f"<{sanitize_uri(p)}>" for p in targets["subjectsOf"])
        q = f"""
        SELECT DISTINCT ?s
        WHERE {{
          GRAPH <{get_data_graph_uri()}> {{
            ?s ?p ?o .
            FILTER (?p IN ({props}))
          }}
        }}"""
        subj_set = {b["s"]["value"]
                    for b in virtuoso.query_select(q)["results"]["bindings"]}
        for n in expanded_nodes:
            if n in subj_set and n in initial_nodes:
                matches.add((n, shape))

    # ── 4. sh:targetObjectsOf ──────────────────────────────────────────
    if targets["objectsOf"]:
        props = ", ".join(f"<{sanitize_uri(p)}>" for p in targets["objectsOf"])
        q = f"""
        SELECT DISTINCT ?o
        WHERE {{
          GRAPH <{get_data_graph_uri()}> {{
            ?s ?p ?o .
            FILTER (?p IN ({props}))
          }}
        }}"""
        obj_set = {b["o"]["value"]
                   for b in virtuoso.query_select(q)["results"]["bindings"]}
        for n in expanded_nodes:
            if n in obj_set and n in initial_nodes:
                matches.add((n, shape))

    return matches


# ---------------------------------------------------------------------------
# 2. Reduced-graph builder
# ---------------------------------------------------------------------------


def build_reduced_graphs(affected_pairs: List[AffectedPair]) -> Tuple[str, List[Triple]]:
    """Materialise a minimal sub-graph sufficient to re-validate the pairs."""

    idx = ShapeIndex()
    temp_graph = f"http://temp.org/data_{uuid.uuid4()}"
    virtuoso.update(f"CREATE SILENT GRAPH <{temp_graph}>")

    if not affected_pairs:
        print("[delta] no affected pairs -> empty reduced graph")
        return temp_graph, []

    allowed_props_map = _compute_allowed_props(
        affected_pairs, idx.shape_paths, idx.closed_shapes, idx.class_like_shapes
    )

    visited: Set[AffectedPair] = set()
    queue   = collections.deque(affected_pairs)

    inserted_total   = 0
    inserted_triples: List[Triple] = []

    while queue:
        batch_pairs = _collect_batch(queue, visited)
        triples = _fetch_triples(
            nodes={n for n, _ in batch_pairs},
            paths={p for pair in batch_pairs for p in allowed_props_map.get(pair, []) or []}
        )

        inserted_triples.extend(triples)
        insert_triples(temp_graph, triples)
        inserted_total += len(triples)

    print(f"[delta] reduced graph <{temp_graph}> <- {inserted_total} triples")
    return temp_graph, inserted_triples

# ---------------------------------------------------------------------------
# helpers used by build_reduced_graphs
# ---------------------------------------------------------------------------


def _compute_allowed_props(
    pairs: List[AffectedPair],
    shape_paths: Dict[str, Set[str]],
    closed_shapes: Set[str],
    class_like_shapes: Set[str],
) -> Dict[AffectedPair, Set[str] | None]:
    m: Dict[AffectedPair, Set[str] | None] = {}
    for node, shape in pairs:
        if shape in closed_shapes:
            m[(node, shape)] = None                       # means “no filter”
        elif shape in class_like_shapes:
            m[(node, shape)] = {RDF_TYPE}
        else:
            allowed = set(shape_paths.get(shape, ()))
            allowed.add(RDF_TYPE)
            m[(node, shape)] = allowed
    return m


def _collect_batch(queue: collections.deque, visited: Set[AffectedPair]) -> List[AffectedPair]:
    batch: List[AffectedPair] = []
    while queue and len(batch) < NODE_BATCH_SIZE:
        pair = queue.popleft()
        if pair not in visited:
            visited.add(pair)
            batch.append(pair)
    return batch


def _iri_list(items: Set[str] | List[str]) -> str:
    return " ".join(f"<{sanitize_uri(i)}>" for i in items if i.startswith("http"))


def _parse_path_expr(expr: str) -> PathExpr:
    expr = expr.strip()
    if expr.startswith("^"):
        return ("inv", expr[1:], None)
    if "/" in expr:
        parts = expr.split("/", 1)
        return ("seq", _parse_path_expr(parts[0]), _parse_path_expr(parts[1]))
    if "|" in expr:
        parts = expr.split("|", 1)
        return ("alt", _parse_path_expr(parts[0]), _parse_path_expr(parts[1]))
    if expr.endswith("*"):
        return ("star", _parse_path_expr(expr[:-1]), None)
    if expr.endswith("+"):
        return ("plus", _parse_path_expr(expr[:-1]), None)
    return expr


def _get_triples(sources: Set[str], predicate: str, graph_uri: str) -> Tuple[List[Triple], Set[str]]:
    s_clause = _iri_list(sources)
    q = f"""
    SELECT ?s ?p ?o
    WHERE {{
      GRAPH <{graph_uri}> {{
        VALUES ?s {{ {s_clause} }}
        ?s <{sanitize_uri(predicate)}> ?o .
      }}
    }}"""
    res = virtuoso.query_select(q)
    triples, next_nodes = [], set()
    for b in res["results"]["bindings"]:
        s = b["s"]["value"]
        p = b["p"]["value"]
        o_val = b["o"]["value"]
        o_typ = b["o"].get("type", "literal")
        if o_typ == "uri":
            obj = (o_val, "uri", None)
            next_nodes.add(o_val)
        elif o_val.startswith("_:"):
            obj = (o_val, "bnode", None)
        else:
            obj = (o_val, "literal", None)
        triples.append((s, p, obj))
    return triples, next_nodes


def _get_inverse_triples(targets: Set[str], predicate: str, graph_uri: str) -> Tuple[List[Triple], Set[str]]:
    o_clause = _iri_list(targets)
    q = f"""
    SELECT ?s ?p ?o
    WHERE {{
      GRAPH <{graph_uri}> {{
        VALUES ?o {{ {o_clause} }}
        ?s <{sanitize_uri(predicate)}> ?o .
      }}
    }}"""
    res = virtuoso.query_select(q)
    triples, prev_nodes = [], set()
    for b in res["results"]["bindings"]:
        s = b["s"]["value"]
        p = b["p"]["value"]
        o_val = b["o"]["value"]
        o_typ = b["o"].get("type", "literal")
        if o_typ == "uri":
            obj = (o_val, "uri", None)
        elif o_val.startswith("_:"):
            obj = (o_val, "bnode", None)
        else:
            obj = (o_val, "literal", None)
        triples.append((s, p, obj))
        prev_nodes.add(s)
    return triples, prev_nodes


def _traverse_path_expr(start_nodes: Set[str], path: PathExpr, graph_uri: str) -> List[Triple]:
    if isinstance(path, str):
        return _get_triples(start_nodes, path, graph_uri)[0]
    kind, left, right = path
    if kind == "inv":
        return _get_inverse_triples(start_nodes, left, graph_uri)[0]
    elif kind == "seq":
        triples1, mid_nodes = _get_triples(start_nodes, left, graph_uri)
        triples2 = _traverse_path_expr(mid_nodes, right, graph_uri)
        return triples1 + triples2
    elif kind == "alt":
        return _traverse_path_expr(start_nodes, left, graph_uri) + _traverse_path_expr(start_nodes, right, graph_uri)
    elif kind == "star" or kind == "plus":
        seen = set(start_nodes)
        worklist = set(start_nodes)
        result = []
        while worklist:
            t, next_nodes = _get_triples(worklist, left, graph_uri)
            result.extend(t)
            new = next_nodes - seen
            seen |= new
            worklist = new
        return result if kind == "plus" else result + []
    return []


def multi_hop_path_traversal(
    start_nodes: Set[str],
    path_exprs: List[str],
    graph_uri: Optional[str] = None,
) -> List[Triple]:
    if not graph_uri:
        graph_uri = get_data_graph_uri()
    all_triples: List[Triple] = []
    for expr in path_exprs:
        parsed = _parse_path_expr(expr)
        all_triples.extend(_traverse_path_expr(start_nodes, parsed, graph_uri))
    return all_triples


def _fetch_atomic_triples(
    nodes: Set[str],
    predicates: Set[str],
    graph_uri: Optional[str] = None
) -> List[Triple]:
    if not nodes or not predicates:
        return []
    if not graph_uri:
        graph_uri = get_data_graph_uri()
    s_clause = _iri_list(nodes)
    p_clause = _iri_list(predicates)
    q = f"""
    SELECT ?s ?p ?o
    WHERE {{
      GRAPH <{graph_uri}> {{
        VALUES ?s {{ {s_clause} }}
        VALUES ?p {{ {p_clause} }}
        ?s ?p ?o .
      }}
    }}"""
    res = virtuoso.query_select(q)
    triples: List[Triple] = []
    for b in res["results"]["bindings"]:
        s = b["s"]["value"]
        p = b["p"]["value"]
        o_val = b["o"]["value"]
        o_typ = b["o"].get("type", "literal")
        if o_typ == "uri":
            obj = (o_val, "uri", None)
        elif o_val.startswith("_:"):
            obj = (o_val, "bnode", None)
        else:
            obj = (o_val, "literal", None)
        triples.append((s, p, obj))
    return triples


def _fetch_triples(
    nodes: Set[str],
    paths: Set[str],
    graph_uri: Optional[str] = None
) -> List[Triple]:
    atomic_preds = set()
    path_exprs = []
    for p in paths:
        if any(x in p for x in ["/", "|", "^", "*", "+"]):
            path_exprs.append(p)
        else:
            atomic_preds.add(p)
    triples: List[Triple] = []
    if atomic_preds:
        triples += _fetch_atomic_triples(nodes, atomic_preds, graph_uri=graph_uri)
    if path_exprs:
        triples += multi_hop_path_traversal(nodes, path_exprs, graph_uri=graph_uri)
    return triples
