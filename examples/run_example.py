from src import run_UpSHACL  # adjust path if needed

run_UpSHACL(
    data_file="data/my_data.ttl",
    shapes_file="data/my_shapes.ttl",
    insert_file="data/insert_batch.ttl",
    delete_file="data/delete_batch.ttl",
    output_reduced_file="results/reduced_graph.ttl",
    verbose=True
)
