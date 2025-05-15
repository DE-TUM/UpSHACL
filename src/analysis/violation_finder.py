import os
import csv
from typing import Set, Tuple
from rdflib import Graph, RDF
from rdflib.namespace import SH

# ---------- helper: extract validation results ----------
def extract_violation_keys(report: Graph) -> Set[Tuple[str, str, str, str]]:
    keys: Set[Tuple[str, str, str, str]] = set()
    visited = set()

    def clean(val):
        return val.toPython() if val else ""

    def collect(vr):
        if vr in visited:
            return
        visited.add(vr)

        if (vr, RDF.type, SH.ValidationResult) not in report:
            return

        keys.add((
            clean(report.value(vr, SH.focusNode)),
            clean(report.value(vr, SH.resultPath)),
            clean(report.value(vr, SH.sourceConstraintComponent)),
            clean(report.value(vr, SH.value)),
        ))

        for detail in report.objects(vr, SH.detail):
            collect(detail)

    for vr in report.subjects(RDF.type, SH.ValidationResult):
        collect(vr)

    return keys



def load_graph(path: str) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g

def compare(path_prev, path_next, path_red) -> dict:
    g_prev = extract_violation_keys(load_graph(path_prev))
    g_next = extract_violation_keys(load_graph(path_next))
    r_next = extract_violation_keys(load_graph(path_red))

    diff    = (g_next - g_prev)
    missing = diff   - r_next
    extra   = r_next - diff

    if missing or extra:
        print("Sample mismatch (max 3 each)")
        for v in list(extra)[:3]:
            print("   extra   :", v)
        for v in list(missing)[:3]:
            print("   missing :", v)

        if missing:
            for v in list(missing)[:3]:
                print("🔍 Checking if really missing:", v)
                for r in r_next:
                    if v[0] == r[0] and v[1] == r[1] and v[2] == r[2] and v[3] == r[3]:
                        print("    ❗ Actually matched with reduced entry:", r)


    return {
        "before": len(g_prev),
        "after":  len(g_next),
        "reduced":len(r_next),
        "diff":   len(diff),
        "missing":len(missing),
        "extra":  len(extra),
    }

# ---------- batch runner ----------
def run_all(
    bases,
    results_dir="",
    reduced_dir="",  # ⬅️ updated to point to your reduced graph dir
    out_csv=""
):
    reduced_graph_map = {
        "full validation report file name" : "reduced validation report file name"
    }

    hdr = ["experiment", "step", "before", "after", "diff", "reduced", "missing", "extra"]
    print(f"[Init] Writing output to: {out_csv}")

    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=hdr)
        wr.writeheader()

        for base in bases:
            print(f"\n[Experiment] {base}")
            for i in range(1, 4):
                print(f"  [Batch {i}] Comparing batch{i - 1} -> batch{i}")

                p0 = os.path.join(results_dir, f"{base}__vr_batch{i - 1}.ttl")
                p1 = os.path.join(results_dir, f"{base}__vr_batch{i}.ttl")

                rg_base = reduced_graph_map.get(base)
                if not rg_base:
                    print(f"    [Error] No reduced graph mapping for {base}")
                    continue

                pr = os.path.join(reduced_dir, f"{rg_base}_rg_{i}.ttl")

                missing = [p for p in (p0, p1, pr) if not os.path.exists(p)]
                if missing:
                    print(f"    [Skipped] Missing files for batch {i}:")
                    for m in missing:
                        print(f"      - {m}")
                    continue

                print(f"    [Loading] Previous: {p0}")
                print(f"    [Loading] Current:  {p1}")
                print(f"    [Loading] Reduced:  {pr}")
                stats = compare(p0, p1, pr)

                wr.writerow({
                    "experiment": base,
                    "step": f"batch{i - 1} -> batch{i}",
                    **stats
                })

                print(
                    f"    [Done] Violations - Prev: {stats['before']}, Curr: {stats['after']}, Reduced: {stats['reduced']}")
                print(
                    f"          Diff: {stats['diff']}, Reduced: {stats['reduced']}, Missing: {stats['missing']}, Extra: {stats['extra']}")

    print(f"\n[Finished] All results written to {out_csv}")



# Experiment prefixes used in validation reports
experiments = [
]

# Run the batch comparison
run_all(
    experiments,
    results_dir="",
    reduced_dir="",
    out_csv="",
)