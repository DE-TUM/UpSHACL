from typing import List, Tuple
from rdflib import Graph, URIRef, BNode, Literal
from src.utils.custom_types import Triple
import os


class DeltaCache:
    inserted_batches: List[List[Triple]] = []
    deleted_batches: List[List[Triple]] = []

    @classmethod
    def set(cls, inserted: List[Triple], deleted: List[Triple]):
        """Legacy single-batch setter (used only if not loading from file)."""
        cls.inserted_batches = [inserted]
        cls.deleted_batches = [deleted]

    @classmethod
    def get_batch(cls, batch_size: int, index: int) -> tuple[List[Triple], List[Triple]]:
        """Return batch from loaded deltas or sliced fallback."""
        if len(cls.inserted_batches) == 1 and len(cls.deleted_batches) == 1:
            start = index * batch_size
            end = start + batch_size
            return cls.inserted_batches[0][start:end], cls.deleted_batches[0][start:end]
        return cls.inserted_batches[index], cls.deleted_batches[index]

    @classmethod
    def get_all(cls) -> tuple[List[Triple], List[Triple]]:
        """Concatenate all batches (useful for cleanup)."""
        inserted = [t for batch in cls.inserted_batches for t in batch]
        deleted = [t for batch in cls.deleted_batches for t in batch]
        return inserted, deleted

    @classmethod
    def load_from_files(cls, base_name: str, num_batches: int, deltas_dir: str = "deltas"):
        """
        Load insert/delete deltas from Turtle files into memory.

        Args:
            base_name: e.g. "EnDe-Lite50without_Ontology__shape30_clean"
            num_batches: number of batches to load
            deltas_dir: directory where TTL files are stored
        """
        cls.inserted_batches.clear()
        cls.deleted_batches.clear()

        def to_object(o) -> Tuple[str, str, str]:  # i.e. third element of your triple
            if isinstance(o, URIRef):
                return (str(o), "uri", None)
            elif isinstance(o, BNode):
                return (str(o), "bnode", None)
            elif isinstance(o, Literal):
                return (str(o), "literal", str(o.datatype) if o.datatype else None)
            else:
                raise ValueError(f"Unsupported RDF object type: {type(o)}")

        for i in range(num_batches):
            insert_path = os.path.join(deltas_dir, f"{base_name}__batch{i}_insert.ttl")
            delete_path = os.path.join(deltas_dir, f"{base_name}__batch{i}_delete.ttl")

            g_insert = Graph()
            g_insert.parse(insert_path, format="turtle")
            insert_triples = [(str(s), str(p), to_object(o)) for s, p, o in g_insert]

            g_delete = Graph()
            g_delete.parse(delete_path, format="turtle")
            delete_triples = [(str(s), str(p), to_object(o)) for s, p, o in g_delete]

            cls.inserted_batches.append(insert_triples)
            cls.deleted_batches.append(delete_triples)
