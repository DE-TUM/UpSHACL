from .parser import parse_shacl_path
from .flatten import flatten_path
from .model import PathExpr


def path_to_sparql_pattern(path_node, shapes_graph, source_var="?s", target_var="?o", depth=3) -> str:
    path_expr = parse_shacl_path(shapes_graph, path_node)
    triples, _ = flatten_path(path_expr, source_var, target_var, depth)
    return "\n".join(triples)


__all__ = ["path_to_sparql_pattern"]
