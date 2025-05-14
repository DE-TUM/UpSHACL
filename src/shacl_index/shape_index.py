from __future__ import annotations
from typing import Dict, Set
from functools import cached_property
from rdflib import Graph, URIRef, Namespace, RDF
from rdflib.term import Node
from ..config_dynamic import get_shapes_graph_uri
from src.config import virtuoso

__all__ = ["ShapeIndex"]

SH = Namespace("http://www.w3.org/ns/shacl#")


class _LazySingleton(type):
    _instances: Dict[str, "ShapeIndex"] = {}

    def __call__(cls, *args, **kwargs):
        key = get_shapes_graph_uri()
        if key is None:
            raise RuntimeError("Shapes graph URI not initialised.")
        if key not in cls._instances:
            cls._instances[key] = super().__call__(key)
            print(f"[ShapeIndex] built for <{key}>")
        return cls._instances[key]


class ShapeIndex(metaclass=_LazySingleton):
    def __init__(self, shapes_graph_uri: str):
        self._g = shapes_graph_uri

    @cached_property
    def target_map(self) -> Dict[str, Dict[str, Set[str]]]:
        q = f"""
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        SELECT ?shape ?kind ?target
        WHERE {{
          GRAPH <{self._g}> {{
            {{
              ?shape a sh:NodeShape ;
                     sh:targetNode ?target .
              BIND("nodes" AS ?kind)
            }} UNION {{
              ?shape a sh:NodeShape ;
                     sh:targetClass ?target .
              BIND("classes" AS ?kind)
            }} UNION {{
              ?shape a sh:NodeShape ;
                     sh:targetSubjectsOf ?target .
              BIND("subjectsOf" AS ?kind)
            }} UNION {{
              ?shape a sh:NodeShape ;
                     sh:targetObjectsOf ?target .
              BIND("objectsOf" AS ?kind)
            }}
          }}
        }}
        """

        res = virtuoso.query(q)
        m: Dict[str, Dict[str, Set[str]]] = {}

        for row in res["results"]["bindings"]:
            shape = row["shape"]["value"]
            kind = row["kind"]["value"]
            target = row["target"]["value"]
            m.setdefault(shape, dict(nodes=set(), classes=set(), subjectsOf=set(), objectsOf=set()))
            m[shape][kind].add(target)

        return m

    @cached_property
    def prop_to_parent_shapes(self) -> Dict[str, Set[str]]:
        g = self._load_shapes_graph()
        mapping: Dict[str, Set[str]] = {}

        for shape in g.subjects(RDF.type, SH.NodeShape):
            for prop in self._extract_all_path_predicates(g, shape):
                mapping.setdefault(str(prop), set()).add(str(shape))

        return mapping

    from rdflib import RDF
    from rdflib.term import Node

    def _extract_all_path_predicates(self, g: Graph, shape_node: Node) -> Set[URIRef]:
        visited = set()
        result = set()

        def recurse(node: Node):
            if node in visited:
                return
            visited.add(node)

            for p, o in g.predicate_objects(node):
                if p == SH.path and isinstance(o, URIRef):
                    result.add(o)

                # ⬇️ Add: handle sh:equals and sh:disjoint explicitly
                elif p in {SH.equals, SH.disjoint} and isinstance(o, URIRef):
                    result.add(o)

                elif p in {SH.or_, SH.and_, SH.xone}:
                    for item in g.items(o):
                        recurse(item)
                elif p == SH.not_:
                    recurse(o)
                elif p == SH.property:
                    recurse(o)

        recurse(shape_node)
        return result

    @cached_property
    def value_sensitive_paths(self) -> Dict[str, Set[str]]:
        """
        Map from path predicate → shapes using that path in a value-sensitive constraint.
        """
        g = self._load_shapes_graph()
        value_constraints = {SH["class"], SH["datatype"], SH["in"], SH["hasValue"], SH["equals"], SH["disjoint"],
                             SH["value"]}
        mapping: Dict[str, Set[str]] = {}

        for shape in g.subjects(RDF.type, SH.NodeShape):
            for ps in g.objects(shape, SH.property):
                path = g.value(ps, SH.path)
                if isinstance(path, URIRef):
                    for val_prop in value_constraints:
                        if (ps, val_prop, None) in g:
                            mapping.setdefault(str(path), set()).add(str(shape))
                            break  # no need to check other value-sensitive constraints
        return mapping


    def _load_shapes_graph(self) -> Graph:
        g = Graph()
        q = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{ GRAPH <{self._g}> {{ ?s ?p ?o }} }}
        """
        res = virtuoso.query(q)
        g.parse(data=res.decode("utf-8"), format="turtle")
        return g

    @cached_property
    def path_predicates(self) -> Set[str]:
        q = f"""
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        SELECT DISTINCT ?p WHERE {{
          GRAPH <{self._g}> {{
            ?s a sh:NodeShape ; sh:property ?ps .
            ?ps sh:path ?p .
          }}
        }}
        """
        r = virtuoso.query(q)
        return {b["p"]["value"] for b in r["results"]["bindings"]}

    @cached_property
    def shape_paths(self) -> Dict[str, Set[str]]:
        g = self._load_shapes_graph()
        result: Dict[str, Set[str]] = {}

        for shape in g.subjects(RDF.type, SH.NodeShape):
            paths = self._extract_all_path_predicates(g, shape)
            if paths:
                result[str(shape)] = {str(p) for p in paths}

        return result

    @cached_property
    def closed_shapes(self) -> Set[str]:
        q = f"""
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        SELECT DISTINCT ?shape
        WHERE {{
          GRAPH <{self._g}> {{
            ?shape a sh:NodeShape ;
                   sh:closed true .
          }}
        }}
        """
        res = virtuoso.query(q)
        return {b["shape"]["value"] for b in res["results"]["bindings"]}

    @cached_property
    def class_like_shapes(self) -> Set[str]:
        q = f"""
           PREFIX sh: <http://www.w3.org/ns/shacl#>
           SELECT DISTINCT ?shape
           WHERE {{
             GRAPH <{self._g}> {{
               {{ ?shape a sh:NodeShape . FILTER EXISTS {{ ?shape sh:class ?_ }} }} UNION
               {{ ?shape a sh:NodeShape . FILTER EXISTS {{ ?shape sh:hasValue ?_ }} }} UNION
               {{ ?shape a sh:NodeShape . FILTER EXISTS {{ ?shape sh:in ?_ }} }}
             }}
           }}
           """
        res = virtuoso.query(q)
        return {b["shape"]["value"] for b in res["results"]["bindings"]}

    def shape_targets(self):
        return self.target_map

    @cached_property
    def node_properties(self) -> Set[str]:
        return set(self.prop_to_parent_shapes)
