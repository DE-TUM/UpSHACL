# config.py

from .store import VirtuosoClient


# Virtuoso endpoints and auth
VIRTUOSO_QUERY_ENDPOINT = "http://localhost:8890/sparql"
VIRTUOSO_UPDATE_ENDPOINT = "http://localhost:8890/sparql"
VIRTUOSO_USERNAME = ""
VIRTUOSO_PASSWORD = ""

DOCKER_CONTAINER_NAME = "" # Add docker container name
DATA_DIR_IN_DOCKER = "/data"
STORAGE_DIR = "" # Leave empty if storage should be within the project
NODE_BATCH_SIZE   = 32  # was 1
CLASS_BATCH_SIZE  = 64   # was 1
MAX_BATCH_SIZE    = 500  # used for VALUES batching elsewhere
PROP_BATCH_SIZE = 1
INCOMING_PROP_BATCH_SIZE = 1

# Shared client instance
virtuoso = VirtuosoClient(
    query_endpoint     = VIRTUOSO_QUERY_ENDPOINT,
    update_endpoint    = VIRTUOSO_UPDATE_ENDPOINT,
    username           = VIRTUOSO_USERNAME,
    password           = VIRTUOSO_PASSWORD,
    docker_container_name = DOCKER_CONTAINER_NAME,
)

# ------------------------------------------------------------------
# publish it to store.virtuoso  ➜ avoids circular import error
# ------------------------------------------------------------------
from . import store as _store  # local import to break the cycle
_store.virtuoso = virtuoso

