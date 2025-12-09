# UpSHACL: Targeted Constraint Validation for Updates over Knowledge Graphs

**UpSHACL** is a SHACL-based validation pipeline designed for efficient constraint checking on evolving RDF graphs. Instead of validating the entire graph after each update, UpSHACL computes a targeted subgraph based on inserted and deleted triples, reducing validation overhead while preserving completeness.

> 📝 **Paper**: [UpSHACL: Targeted Constraint Validation for Updates over Knowledge Graphs](https://dl.acm.org/doi/10.1007/978-3-032-09527-5_7)
> 📄 **DOI**: 10.1007/978-3-032-09527-5_7

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Usage](#usage)
4. [Parameters](#parameters)
5. [Datasets](#datasets)
6. [License](#license)

---

## Overview

This repository implements **UpSHACL**, as described in our ISWC 2025 submission (currently under double-blind review). The goal is to minimize unnecessary revalidation by isolating the subset of the RDF graph affected by update deltas.

**Key Features:**

* Accepts full data graph, SHACL shapes graph, and update deltas (inserts/deletes)
* Computes a reduced subgraph for validation
* Compatible with any standard SHACL engine (e.g., PySHACL)

---

## Installation

### Prerequisites

* Python ≥ 3.9
* Docker (for running Virtuoso Open Source)

### Setup Instructions

1. **Clone the Repository**

   ```bash
   git clone https://github.com/DE-TUM/UpSHACL
   cd UpSHACL
   ```

2. **Start Virtuoso via Docker**

   ```bash
   docker run -d \
     --name upshacl-virtuoso \
     -p 8890:8890 \
     -v "$(pwd)/data":/data \
     openlink/virtuoso-opensource-7
   ```

3. **Configure Connection (Optional)**
   Update `src/config.py` if needed:

   * `VIRTUOSO_CONTAINER_NAME = "upshacl-virtuoso"`
   * Set your `DBA_USERNAME` and `DBA_PASSWORD`

4. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

### Run the UpSHACL Pipeline

```python
from src import run_UpSHACL

run_UpSHACL(
    data_file="data/my_data.ttl",
    shapes_file="data/my_shapes.ttl",
    insert_file="data/inserts.ttl",
    delete_file="data/deletes.ttl",
    output_reduced_file="results/reduced.ttl",
    verbose=True
)
```
Parameters

| Argument              | Description                                  |
| --------------------- | -------------------------------------------- |
| `data_file`           | Path to the full input RDF data graph (.ttl) |
| `shapes_file`         | Path to the SHACL shapes graph (.ttl)        |
| `insert_file`         | RDF triples to insert (update delta)         |
| `delete_file`         | RDF triples to delete (update delta)         |
| `output_reduced_file` | Path to save the reduced subgraph (.ttl)     |
| `verbose`             | Enables detailed logs if `True`              |

### Run All Experiments (Windows only)
Note: datasets are automatically downloaded if not already present in `/data` folder
```bash
./run_all_experiments
```

### Generate Plots and Tables

Scripts for analysis and plotting are available under:

```bash
/analysis/
```

---

## Datasets

### LUBM

* Shapes & Data graphs: [Link (University of Hannover)](https://data.uni-hannover.de/dataset/trav-shacl-benchmarks-experimental-settings-and-evaluation/resource/3dcefa6d-d57e-4de7-bc11-56227ae4e119?inner_span=True)

### DBpedia

* Data graphs: [Zenodo (DB50–1000)](https://zenodo.org/records/12798851)
* Shapes graph: available at `data/shape30_clean.ttl`

---

## License

This repository is released anonymously for double-blind peer review. License details will be made available after acceptance.

