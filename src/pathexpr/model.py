from dataclasses import dataclass
from typing import Optional, List

@dataclass(frozen=True)
class PathExpr:
    predicate: Optional[str] = None
    inverse: Optional["PathExpr"] = None
    zero_or_more: Optional["PathExpr"] = None
    one_or_more: Optional["PathExpr"] = None
    zero_or_one: Optional["PathExpr"] = None
    seq: Optional[List["PathExpr"]] = None
    alt: Optional[List["PathExpr"]] = None
