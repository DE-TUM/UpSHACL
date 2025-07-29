from rdflib import Graph
from pyshacl import validate


def load_graph_from_ttl(filename):
    g = Graph()
    g.parse(filename)
    return g




if __name__ == '__main__':
    dg = load_graph_from_ttl('paper_data_graph.ttl')
    sg = load_graph_from_ttl('paper_shapes_graph.ttl')
    a, b, c = validate(dg, sg)
