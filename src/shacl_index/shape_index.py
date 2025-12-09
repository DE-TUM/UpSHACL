from __future__ import annotations

from typing import Dict, Set, Tuple, Optional
from functools import cached_property
from rdflib import Graph, URIRef, BNode, Namespace, RDF
from rdflib.term import Node

from ..config_dynamic import get_shapes_graph_uri
from ..pathexpr import path_to_sparql_pattern

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
    _override_graph: Optional[Graph] = None

    @classmethod
    def override_with_graph(cls, g: Graph):
        cls._override_graph = g

    def __init__(self, shapes_graph_uri: str):
        self._g = shapes_graph_uri

    @cached_property
    def graph(self) -> Graph:
        return self._load_shapes_graph()

    def _load_shapes_graph(self) -> Graph:
        if self._override_graph is not None:
            return self._override_graph
        raise RuntimeError("No SHACL graph override set. Use `ShapeIndex.override_with_graph(...)` before first call.")

    @cached_property
    def target_map(self) -> Dict[Node, Dict[str, Set[str]]]:
        g = self.graph
        m: Dict[Node, Dict[str, Set[str]]] = {}
        for shape in g.subjects(RDF.type, SH.NodeShape):
            for pred, kind in [
                (SH.targetNode, "nodes"),
                (SH.targetClass, "classes"),
                (SH.targetSubjectsOf, "subjectsOf"),
                (SH.targetObjectsOf, "objectsOf"),
            ]:
                for target in g.objects(shape, pred):
                    m.setdefault(shape, dict(nodes=set(), classes=set(), subjectsOf=set(), objectsOf=set()))
                    m[shape][kind].add(str(target))
        return m

    @cached_property
    def prop_to_parent_shapes(self) -> Dict[Node, Set[Node]]:
        g = self.graph
        mapping: Dict[Node, Set[Node]] = {}
        for shape in g.subjects(RDF.type, SH.NodeShape):
            for prop in self._extract_all_path_predicates(g, shape):
                mapping.setdefault(prop, set()).add(shape)
        return mapping

    def _extract_all_path_predicates(self, g: Graph, shape_node: Node) -> Set[Node]:
        visited = set()
        result = set()

        def recurse(node: Node):
            if node in visited:
                return
            visited.add(node)
            for p, o in g.predicate_objects(node):
                if p == SH.path:
                    result.add(o)
                elif p in {SH.equals, SH.disjoint}:
                    result.add(o)
                elif p in {SH.or_, SH.and_, SH.xone}:
                    for item in g.items(o):
                        recurse(item)
                elif p == SH.not_ or p == SH.property:
                    recurse(o)

        recurse(shape_node)
        return result

    @cached_property
    def value_sensitive_paths(self) -> Dict[Node, Set[Node]]:
        g = self.graph
        value_constraints = {SH["class"], SH["datatype"], SH["in"], SH["hasValue"], SH["equals"], SH["disjoint"], SH["value"]}
        mapping: Dict[Node, Set[Node]] = {}
        for shape in g.subjects(RDF.type, SH.NodeShape):
            for ps in g.objects(shape, SH.property):
                path = g.value(ps, SH.path)
                if path is not None:
                    for val_prop in value_constraints:
                        if (ps, val_prop, None) in g:
                            mapping.setdefault(path, set()).add(shape)
                            break
        return mapping

    @cached_property
    def path_predicates(self) -> Set[Node]:
        g = self.graph
        return {
            g.value(ps, SH.path)
            for shape in g.subjects(RDF.type, SH.NodeShape)
            for ps in g.objects(shape, SH.property)
            if g.value(ps, SH.path) is not None
        }

    @cached_property
    def shape_paths(self) -> Dict[Node, Set[Node]]:
        g = self.graph
        result: Dict[Node, Set[Node]] = {}
        for shape in g.subjects(RDF.type, SH.NodeShape):
            paths = self._extract_all_path_predicates(g, shape)
            if paths:
                result[shape] = paths
        return result

    @cached_property
    def closed_shapes(self) -> Set[str]:
        g = self.graph
        return {
            str(shape)
            for shape in g.subjects(RDF.type, SH.NodeShape)
            if (shape, SH.closed, None) in g
            and str(g.value(shape, SH.closed)).lower() == "true"
        }

    @cached_property
    def class_like_shapes(self) -> Set[str]:
        g = self.graph
        result = set()
        for shape in g.subjects(RDF.type, SH.NodeShape):
            if any((shape, pred, None) in g for pred in [SH["class"], SH["hasValue"], SH["in"]]):
                result.add(str(shape))
        return result

    def shape_targets(self):
        return self.target_map

    @cached_property
    def node_properties(self) -> Set[Node]:
        return {p for p in self.prop_to_parent_shapes.keys()}

    @cached_property
    def shape_triple_patterns(self) -> Dict[str, Set[str]]:
        """Return SPARQL triple patterns needed for each shape.
        
        Returns:
            Dict mapping shape URI to set of SPARQL triple patterns.
            Patterns include property paths and rdf:type for target classes.
        """
        shape_to_paths = self.shape_paths
        triple_map: Dict[str, Set[str]] = {}
        
        for shape, targets in self.target_map.items():
            shape_str = str(shape)
            patterns = set()
            
            # Add rdf:type patterns for target classes
            for cls in targets.get('classes', set()):
                patterns.add(f"?s <{RDF.type}> <{cls}> .")
            
            # Add property path patterns
            if shape in shape_to_paths:
                for path_node in shape_to_paths[shape]:
                    pattern = path_to_sparql_pattern(path_node, self.graph)
                    patterns.add(pattern)
            
            if patterns:
                triple_map[shape_str] = patterns
        
        return triple_map
