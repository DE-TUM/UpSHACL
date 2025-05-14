# UpSHACL: Targeted Constraint Validation for Updates over Knowledge Graphs


**UpSHACL** is a SHACL-based pipeline for efficient validation of evolving RDF graphs. It computes a reduced subgraph based on inserted and deleted triples, enabling significant performance improvements over full revalidation.

> 📝 **Paper Link**: [TBA]  
> DOI: [TBA]

---

## Table of Contents
1. [Overview](#overview)
2. [Installation](#installation)
3. [Usage](#usage)
4. [Parameters](#parameters)

---

## Overview

This repository contains the implementation of **UpSHACL**, as described in our ISWC 2025 submission (double-blind, link to follow after review). The goal of UpSHACL is to avoid unnecessary revalidation of large RDF graphs by isolating and validating only the relevant subgraph based on update deltas.

UpSHACL:
- Takes as input a data graph, shapes graph, and update deltas (insertions and deletions)
- Computes a **reduced validation subgraph**
- Supports any standard SHACL validator for downstream validation

---

## Installation

### Prerequisites
- Python ≥ 3.9
- [Virtuoso Open Source Edition](https://hub.docker.com/r/openlink/virtuoso-opensource-7) (running via Docker)

### Setup Instructions
1. Clone this repository:
   ```bash
   git clone https://github.com/[your-repo]/UpSHACL
   cd UpSHACL
   ```

2. Start Virtuoso using Docker:

   ```bash
   docker run -d \
     --name my-virtuoso \
     -p 8890:8890 \
     -v "$(pwd)/data":/data \
     openlink/virtuoso-opensource-7

   ```

3. Edit your `src/config.py`:

   * Set `VIRTUOSO_CONTAINER_NAME = "my-virtuoso"` (or your custom container name)
   * Set your Virtuoso `DBA_USERNAME` and `DBA_PASSWORD`

4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

You can run the pipeline using:

```python
from src import run_UpSHACL  # adjust path if needed

run_UpSHACL(
    data_file="data/my_data.ttl",
    shapes_file="data/my_shapes.ttl",
    insert_file="data/insert_batch.ttl",
    delete_file="data/delete_batch.ttl",
    output_reduced_file="results/reduced_graph.ttl",
    verbose=True
)
```

---

## Parameters

| Argument              | Description                                          |
| --------------------- | ---------------------------------------------------- |
| `data_file`           | Path to the full data graph (.ttl)                   |
| `shapes_file`         | Path to the SHACL shapes graph (.ttl)                |
| `insert_file`         | RDF triples to insert (delta)                        |
| `delete_file`         | RDF triples to delete (delta)                        |
| `output_reduced_file` | Output path for the reduced validation subgraph      |
| `verbose`             | If `True`, logs each step to stdout for transparency |

---

## License

This repository is released anonymously for double-blind peer review. License details will be added upon acceptance.

