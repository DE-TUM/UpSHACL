import subprocess
from SPARQLWrapper import SPARQLWrapper, JSON, N3, TURTLE, BASIC, POST
import logging

from rdflib import Graph

logging.basicConfig(level=logging.INFO)

class VirtuosoClient:
    def __init__(self, query_endpoint: str, update_endpoint: str, username: str, password: str, docker_container_name: str):
        # Query SPARQL
        self.query_sparql = SPARQLWrapper(query_endpoint)
        self.query_sparql.setHTTPAuth(BASIC)
        self.query_sparql.setCredentials(username, password)
        self.query_sparql.setMethod(POST)

        # Update SPARQL
        self.update_sparql = SPARQLWrapper(update_endpoint)
        self.update_sparql.setHTTPAuth(BASIC)
        self.update_sparql.setCredentials(username, password)
        self.update_sparql.setMethod(POST)

        self.username = username
        self.password = password
        self.docker_container_name = docker_container_name

        print(f"Query endpoint: {self.query_sparql.endpoint}")
        print(f"Update endpoint: {self.update_sparql.endpoint}")
        print(f"Auth: {username}/{password}")

        if not self.verify_admin_privileges():
            raise PermissionError(
                "The provided Virtuoso credentials do not have admin rights. Please check username/password.")

    # --- Query Methods ---

    def verify_admin_privileges(self):
        """
        Verify if the current user has admin privileges by running a harmless test update.
        """
        try:
            test_query = """
            INSERT DATA {
                GRAPH <http://example.org/admin_test> {
                    <http://example.org/adminTest> <http://example.org/prop> "test" .
                }
            }
            """
            self.update(test_query)

            # Clean up
            cleanup_query = """
            DELETE DATA {
                GRAPH <http://example.org/admin_test> {
                    <http://example.org/adminTest> <http://example.org/prop> "test" .
                }
            }
            """
            self.update(cleanup_query)

            logging.info("Admin privileges verified.")
            return True
        except Exception as e:
            logging.error(f"Admin privilege verification failed: {e}")
            return False


    def query(self, query: str):
        """
        Auto-detect query type and return the appropriate format.
        """
        query_type = self._detect_query_type(query)

        if query_type in {"construct", "describe"}:
            return self.query_rdf(query)
        elif query_type in {"select", "ask"}:
            return self.query_select(query)
        else:
            raise ValueError(f"Unsupported or unknown SPARQL query type: {query_type}")

    def query_select(self, query: str):
        """
        For SELECT and ASK queries (returns dict).
        """
        self.query_sparql.setQuery(query)
        self.query_sparql.setReturnFormat(JSON)
        logging.debug("Running SELECT/ASK query.")
        return self.query_sparql.query().convert()

    def query_rdf(self, query: str):
        """
        For CONSTRUCT / DESCRIBE queries (returns rdflib-compatible XML).
        """
        self.query_sparql.setQuery(query)
        self.query_sparql.setReturnFormat(TURTLE)  # XML is safer and well-supported
        logging.debug("Running CONSTRUCT/DESCRIBE query.")
        response = self.query_sparql.query().response
        # print(f"Virtuoso response Content-Type: {response.info().get_content_type()}")
        return response.read()

    # --- Update Method ---

    def update(self, update_query: str):
        self.update_sparql.setQuery(update_query)
        logging.debug("Running UPDATE query.")
        return self.update_sparql.query()

    # --- Helpers ---

    def _detect_query_type(self, query: str) -> str:
        """
        Detect the type of SPARQL query: SELECT, ASK, CONSTRUCT, DESCRIBE
        """
        stripped_query = query.strip().lower()

        for qtype in ("select", "ask", "construct", "describe"):
            if stripped_query.startswith(qtype):
                return qtype

        # Virtuoso allows `define sql:big-data-const 0` at the top, so skip lines
        lines = stripped_query.splitlines()
        for line in lines:
            for qtype in ("select", "ask", "construct", "describe"):
                if line.strip().startswith(qtype):
                    return qtype

        raise ValueError("Could not detect SPARQL query type.")

    def check_graph_exists(self, graph_uri: str) -> bool:
        ask_query = f"ASK {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
        result = self.query_select(ask_query)
        return result.get("boolean", False)

    def ensure_graph_exists(self, graph_uri: str):
        if not self.check_graph_exists(graph_uri):
            logging.info(f"Graph <{graph_uri}> does not exist. Creating.")
            create_query = f"""
            INSERT DATA {{
                GRAPH <{graph_uri}> {{
                    <http://example.org/dummy> <http://example.org/dummyProp> "dummy" .
                }}
            }}
            """
            self.update(create_query)

            # Clean up dummy
            cleanup_query = f"""
            DELETE DATA {{
                GRAPH <{graph_uri}> {{
                    <http://example.org/dummy> <http://example.org/dummyProp> "dummy" .
                }}
            }}
            """
            self.update(cleanup_query)

            logging.info(f"Graph <{graph_uri}> created.")
        else:
            logging.info(f"Graph <{graph_uri}> already exists.")

    def is_container_running(self) -> bool:
        """Check if the Virtuoso Docker container is running."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.docker_container_name],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip() == "true"
        except subprocess.CalledProcessError:
            return False


    def get_graph_as_rdflib(self, graph_uri: str) -> Graph:
        """
        Retrieve a full named graph from Virtuoso as an rdflib.Graph.
        """
        construct_query = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}
        """
        rdf_data = self.query_rdf(construct_query)
        g = Graph()
        g.parse(data=rdf_data.decode("utf-8"), format="turtle")
        return g