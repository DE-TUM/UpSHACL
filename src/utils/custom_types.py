# custom_types.py
from typing import List, Tuple
from dataclasses import dataclass

Triple = Tuple[str, str, Tuple[str, str, str]]  # (subject, predicate, (object_value, object_type, object_meta))

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
