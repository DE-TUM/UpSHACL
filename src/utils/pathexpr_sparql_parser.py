from src.utils.custom_types import PathExpr


def path_expr_to_sparql(p: PathExpr) -> str:
    if p.predicate:
        return f"<{p.predicate}>"

    if p.inverse:
        return f"^{path_expr_to_sparql(p.inverse)}"

    if p.zero_or_more:
        return f"{_wrap_if_complex(p.zero_or_more)}*"

    if p.one_or_more:
        return f"{_wrap_if_complex(p.one_or_more)}+"

    if p.zero_or_one:
        return f"{_wrap_if_complex(p.zero_or_one)}?"

    if p.seq:
        return "/".join(path_expr_to_sparql(e) for e in p.seq)

    if p.alt:
        return "|".join(path_expr_to_sparql(e) for e in p.alt)

    raise ValueError(f"Unknown or malformed PathExpr: {p}")


def _wrap_if_complex(subexpr: PathExpr) -> str:
    """Wrap subexpression in parentheses if needed."""
    if subexpr.predicate or subexpr.inverse:
        return path_expr_to_sparql(subexpr)
    return f"({path_expr_to_sparql(subexpr)})"
