# sanitizer.py
import re
from typing import List, Tuple
from urllib.parse import urlsplit, urlunsplit, quote, unquote
from .custom_types import Triple
from rdflib import Graph, URIRef

ALLOWED = "/:()?#[]{}=&"          # extra chars we want to keep unescaped

def sanitize_graph(graph: Graph) -> Graph:
    sanitized = Graph()
    for s, p, o in graph:
        s_new = URIRef(sanitize_uri(str(s))) if isinstance(s, URIRef) else s
        p_new = URIRef(sanitize_uri(str(p))) if isinstance(p, URIRef) else p
        o_new = URIRef(sanitize_uri(str(o))) if isinstance(o, URIRef) else o
        sanitized.add((s_new, p_new, o_new))
    return sanitized



def sanitize_uri(uri: str) -> str:
    if not isinstance(uri, str):
        uri = str(uri)
    uri = uri.strip()

    # 1) remove manual back-slash escapes around ( ) [ ] { }
    uri = re.sub(r'\\([()[\]{}])', r'\1', uri)

    parts = urlsplit(uri)

    # 2) decode once, so we don’t double-encode later
    path     = unquote(parts.path)
    query    = unquote(parts.query)
    fragment = unquote(parts.fragment)

    # 3) re-encode everything that is not already allowed
    safe_path     = quote(path,     safe=ALLOWED)
    safe_query    = quote(query,    safe=ALLOWED + "=&")   # keep = &
    safe_fragment = quote(fragment, safe=ALLOWED)

    return urlunsplit((
        parts.scheme,
        parts.netloc.encode("idna").decode(),  # puny-code any non-ASCII host name
        safe_path, safe_query, safe_fragment
    ))


def percent_encode_uris_in_attributes(text: str) -> str:
    def encode_uri(match):
        full = match.group(0)
        uri = match.group(1)
        from urllib.parse import urlsplit, urlunsplit, quote
        parts = urlsplit(uri)
        encoded_path = quote(parts.path, safe="/:()?#[]{}=&")
        encoded = urlunsplit((parts.scheme, parts.netloc, encoded_path, parts.query, parts.fragment))
        return full.replace(uri, encoded)

    return re.sub(r'(rdf:(about|resource))="([^"]+)"', encode_uri, text)



def sanitize_rdfxml_text(text: str) -> str:
    text = re.sub(r'\\([()[\]{}])', r'\1', text)
    text = text.replace('%5C(', '(').replace('%5C)', ')')
    text = text.replace('%5c(', '(').replace('%5c)', ')')
    text = re.sub(r'&amp;([a-z]+);', r'&\1;', text)
    text = percent_encode_uris_in_attributes(text)
    # Remove unexpected null characters (can happen with weird encodings)
    text = text.replace('\x00', '')

    # Ensure it starts with a proper XML declaration or <rdf:RDF>
    if not text.lstrip().startswith("<?xml") and "<rdf:RDF" not in text:
        raise ValueError("Not valid RDF/XML content. Aborting sanitization to prevent breakage.")

    return text


def format_object(obj: tuple[str, str, str]) -> str:
    """
    Format an RDF object for SPARQL insertion using simplified types: 'uri', 'literal', 'bnode'.
    """
    value, obj_type, extra = obj

    if obj_type == "uri":
        return f"<{sanitize_uri(value)}>"
    elif obj_type == "bnode":
        return value  # e.g., _:b123
    elif obj_type == "literal":
        escaped = (
            value.replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', '\\n')
            .replace('\r', '')
        )
        if extra:
            # Clean malformed datatype URIs like ^^<...>
            if extra.startswith("^^"):
                return f'"{escaped}"^^<{extra[2:]}>'
            else:
                return f'"{escaped}"{extra}'

        else:
            return f'"{escaped}"'

    else:
        raise ValueError(f"Unknown object type: {obj_type}")


def build_sparql_triples(triples: List[Triple]) -> List[str]:
    """
    Build a list of SPARQL triple strings from internal triple representations.

    Args:
        triples: List of triples (subject, predicate, object), where object is itself a (value, type, extra) tuple.

    Returns:
        List of formatted SPARQL triples as strings.
    """
    return [
        f"<{sanitize_uri(s)}> <{sanitize_uri(p)}> {format_object(o)} ."
        for s, p, o in triples
    ]


def normalize_triple(triple):
    s, p, o = triple
    s_norm = URIRef(sanitize_uri(str(s))) if isinstance(s, URIRef) else s
    p_norm = URIRef(sanitize_uri(str(p))) if isinstance(p, URIRef) else p
    o_norm = URIRef(sanitize_uri(str(o))) if isinstance(o, URIRef) else o
    return (s_norm, p_norm, o_norm)


def normalize_graph(graph: Graph) -> set:
    return set(normalize_triple(t) for t in graph)
