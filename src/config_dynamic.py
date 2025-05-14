_data_graph_uri = None
_shapes_graph_uri = None

def set_graph_uris(data_uri, shapes_uri):
    global _data_graph_uri, _shapes_graph_uri
    _data_graph_uri = data_uri
    _shapes_graph_uri = shapes_uri

def get_data_graph_uri():
    return _data_graph_uri

def get_shapes_graph_uri():
    return _shapes_graph_uri
