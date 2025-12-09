from __future__ import annotations

from rdflib import Graph, URIRef, BNode
from rdflib.term import Node
from typing import Set, Tuple, List, Optional, Dict, Union

from src.config_dynamic import get_data_graph_uri, get_shapes_graph_uri
from src.store import virtuoso
from src.utils.custom_types import PathExpr, Triple
from src.utils.path_flattener import flatten_path
from src.utils.path_parser import parse_shacl_path


class SH:
    path = URIRef("http://www.w3.org/ns/shacl#path")
    equals = URIRef("http://www.w3.org/ns/shacl#equals")
    disjoint = URIRef("http://www.w3.org/ns/shacl#disjoint")
    or_ = URIRef("http://www.w3.org/ns/shacl#or")
    and_ = URIRef("http://www.w3.org/ns/shacl#and")
    xone = URIRef("http://www.w3.org/ns/shacl#xone")
    not_ = URIRef("http://www.w3.org/ns/shacl#not")
    property = URIRef("http://www.w3.org/ns/shacl#property")
class PathProcessor:
    def __init__(self):
        self.data_graph_uri = get_data_graph_uri()
        self.shapes_graph_uri = get_shapes_graph_uri()
        self._visited_shapes: Set[Node] = set()
        self._path_exprs: Dict[Node, Set[PathExpr]] = {}

    def _load_shapes_graph(self) -> Graph:
        return virtuoso.get_graph_as_rdflib(self.shapes_graph_uri)

    def extract_path_exprs(self, shape_node: Node) -> Set[PathExpr]:
        if shape_node in self._path_exprs:
            return self._path_exprs[shape_node]

        shapes_graph = self._load_shapes_graph()
        self._visited_shapes.clear()
        paths: Set[PathExpr] = set()
        self._recurse(shape_node, paths, shapes_graph)
        self._path_exprs[shape_node] = paths
        return paths

    def _recurse(self, node: Node, paths: Set[PathExpr], graph: Graph):
        if node in self._visited_shapes:
            return
        self._visited_shapes.add(node)

        for p, o in graph.predicate_objects(node):
            if p == SH.path:
                parsed = parse_shacl_path(graph, o)
                if parsed:
                    paths.add(parsed)
            elif p in {SH.equals, SH.disjoint} and isinstance(o, URIRef):
                paths.add(PathExpr(predicate=str(o)))
            elif p in {SH.or_, SH.and_, SH.xone}:
                for item in graph.items(o):
                    self._recurse(item, paths, graph)
            elif p == SH.not_:
                self._recurse(o, paths, graph)
            elif p == SH.property:
                self._recurse(o, paths, graph)

    def _traverse_path_expr(self, start_nodes: Set[str], path: PathExpr, depth: int = 3) -> List[Triple]:
        triples: List[Triple] = []
        for src in start_nodes:
            path_triples, _ = flatten_path(path, f"<{src}>", "?end", depth)
            body = "\n".join(path_triples)
            query = f"""
            SELECT * WHERE {{
              GRAPH <{self.data_graph_uri}> {{
                {body}
              }}
            }}"""
            res = virtuoso.query_select(query)
            for b in res["results"]["bindings"]:
                for k in b:
                    if k.startswith("v"):
                        s = b.get(f"v{int(k[1:]) - 1}", b.get("s", {"value": None}))['value']
                        o = b[k]["value"]
                        if s and o:
                            triples.append((s, "?", (o, "uri", None)))
        return triples

    def traverse_all(self, start_nodes: Set[str], paths: Set[PathExpr], depth: int = 3) -> List[Triple]:
        all_triples = []
        for path_expr in paths:
            all_triples.extend(self._traverse_path_expr(start_nodes, path_expr, depth))
        return all_triples