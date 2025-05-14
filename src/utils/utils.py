import os
from rdflib import Graph, XSD, URIRef, BNode, Literal
from src.utils.custom_types import Triple
from src.utils.sanitizer import normalize_triple

def make_validation_report_path(csv_file: str, batch_i: int, kind: str) -> str:
    """
    kind: 'fg' for full graph, 'rg' for reduced graph
    batch_i: 0 for baseline full graph, i>0 for updates
    """
    directory = os.path.dirname(csv_file)
    base = os.path.splitext(os.path.basename(csv_file))[0]
    return os.path.join(directory, f"{base}_{kind}_{batch_i}.ttl")





import os
from rdflib import Graph
from src.utils.custom_types import Triple
from src.utils.sanitizer import sanitize_uri

def materialize_triple(s: str, p: str, o_val: str, o_type: str, extra: str):
    subj = URIRef(sanitize_uri(s))
    pred = URIRef(sanitize_uri(p))

    if o_type == 'uri':
        obj = URIRef(sanitize_uri(o_val))
    elif o_type == 'bnode':
        obj = BNode(o_val)
    elif o_type == 'literal':
        if extra and extra.startswith("@"):
            obj = Literal(o_val, lang=extra[1:])
        elif extra and extra.startswith("^^"):
            dt_uri = extra[2:]
            datatype = URIRef(dt_uri)
            try:
                if datatype in {
                    XSD.double, XSD.float, XSD.decimal,
                    XSD.integer, XSD.nonNegativeInteger, XSD.positiveInteger,
                    XSD.int, XSD.long, XSD.unsignedInt, XSD.unsignedShort,
                    XSD.short, XSD.byte
                }:
                    val = float(o_val) if datatype in {XSD.float, XSD.double, XSD.decimal} else int(o_val)
                    obj = Literal(val, datatype=datatype)
                else:
                    obj = Literal(o_val, datatype=datatype)
            except ValueError:
                obj = Literal(o_val, datatype=datatype)  # fallback
        else:
            obj = Literal(o_val)
    else:
        raise ValueError(f"Unknown object type: {o_type}")

    return (subj, pred, obj)



def save_delta_batch_as_ttl(
    batch_index: int,
    inserted: list[Triple],
    deleted: list[Triple],
    data_file: str,
    shapes_file: str,
    out_dir: str = "deltas"
):
    """
    Save one batch of inserted & deleted triples as TTL files.
    The files are named based on data+shapes file and batch index.
    """
    os.makedirs(out_dir, exist_ok=True)

    def normalize_filename(path: str) -> str:
        return os.path.basename(path).replace(".ttl", "").replace("(", "").replace(")", "").replace(" ", "").replace("/", "_")

    prefix = f"{normalize_filename(data_file)}__{normalize_filename(shapes_file)}"
    ins_path = os.path.join(out_dir, f"{prefix}__batch{batch_index}_insert.ttl")
    del_path = os.path.join(out_dir, f"{prefix}__batch{batch_index}_delete.ttl")

    g_ins = Graph()
    for s, p, (val, typ, extra) in inserted:
        g_ins.add(materialize_triple(s, p, val, typ, extra))
    g_ins.serialize(destination=ins_path, format="turtle")

    g_del = Graph()
    for s, p, (val, typ, extra) in deleted:
        g_del.add(materialize_triple(s, p, val, typ, extra))
    g_del.serialize(destination=del_path, format="turtle")


