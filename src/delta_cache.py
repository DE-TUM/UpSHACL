# src/delta_cache.py
from typing import List
from src.utils.custom_types import Triple

class DeltaCache:
    inserted: List[Triple] = []
    deleted: List[Triple] = []

    @classmethod
    def set(cls, inserted: List[Triple], deleted: List[Triple]):
        cls.inserted = inserted
        cls.deleted = deleted

    @classmethod
    def get_batch(cls, batch_size: int, index: int) -> tuple[List[Triple], List[Triple]]:
        start = index * batch_size
        end = start + batch_size
        return cls.inserted[start:end], cls.deleted[start:end]

    @classmethod
    def get_all(cls) -> tuple[List[Triple], List[Triple]]:
        return cls.inserted, cls.deleted
