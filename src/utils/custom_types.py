# custom_types.py
from typing import List, Tuple, Union, Optional
from dataclasses import dataclass

Triple = Tuple[str, str, Tuple[str, str, str]]  # (subject, predicate, (object_value, object_type, object_meta))
# PathExpr = Union[str, Tuple]
Object = Tuple[str, str, Optional[str]]
@dataclass
class ValidationResults:
    run_id: str
    timestamp: str
    timings: dict
    affected_pairs: List[Tuple[str, str]]
    delta_insert: List[Triple]
    delta_delete: List[Triple]
    full_violations: set
    filtered_full_violations: set
    reduced_violations: set
    missing_violations: set
    extra_violations: set
    full_data_triples: int
    reduced_data_triples: int
    full_shapes_triples: int
    reduced_shapes_triples: int
    speedup_factor: float


@dataclass(frozen=True)
class PathExpr:
    predicate: Optional[str] = None
    inverse: Optional["PathExpr"] = None
    zero_or_more: Optional["PathExpr"] = None
    one_or_more: Optional["PathExpr"] = None
    zero_or_one: Optional["PathExpr"] = None
    seq: Optional[List["PathExpr"]] = None
    alt: Optional[List["PathExpr"]] = None
