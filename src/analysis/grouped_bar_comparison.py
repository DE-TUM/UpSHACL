import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator

# === Group mapping ===
groups = {
    "group1": [
        ("csv file", "dataset name"),
    ],
    "group2": [
        ("csv file", "dataset name"),

    ]
}



# === Shared constants ===
LABEL_SIZE    = 28
TICK_SIZE     = 24
LEGEND_SIZE   = 28
CSV_FOLDER    = "fresh_results"
RESULTS_FOLDER = "results"
OUTPUT_FOLDER = "composite_images_fresh"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# === Legend storage ===
legend_handles = []
legend_labels  = []

# exact column names
TIMING_COLS = {
    'shapes_load': 'timing_Load shapes file',
    'full_val':    'timing_Full validation',
    'ttl_load':    'timing_Load reduced graph from ttl',
    'aff_pairs':   'timing_Affected pairs computation',
    'red_build':   'timing_Reduced graphs building',
    'red_val':     'timing_Reduced validation',
    'virtuoso':    'timing_Load full graph into Virtuoso'
}

# === Compute global y-limits based on averaged bar values ===
all_averages = []

for group_entries in groups.values():
    for csv_file, _ in group_entries:
        df = pd.read_csv(os.path.join(CSV_FOLDER, csv_file))
        results_df = pd.read_csv(os.path.join(RESULTS_FOLDER, csv_file))
        df[TIMING_COLS['full_val']] = results_df[TIMING_COLS['full_val']]

        full_no_ttl = df[TIMING_COLS['shapes_load']] + df[TIMING_COLS['full_val']]
        pipeline = (
            df[TIMING_COLS['aff_pairs']] +
            df[TIMING_COLS['red_build']] +
            df[TIMING_COLS['ttl_load']] +
            df[TIMING_COLS['red_val']] +
            df[TIMING_COLS['shapes_load']]
        )
        all_averages.extend([full_no_ttl.mean(), pipeline.mean()])

# Pad in log space
global_min = min([x for x in all_averages if x > 0])
global_max = max(all_averages)
pad_factor = (global_max / global_min) ** 0.05
ymin_padded = global_min / pad_factor
ymax_padded = global_max * pad_factor
global_limits = (ymin_padded, ymax_padded)

def plot_all_shapes_grouped(group_entries, y_limits, output_path):
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import defaultdict

    plt.style.use('seaborn-v0_8-muted')

    # === Group by shape key (e.g., name1, name2, etc.)
    grouped = defaultdict(list)
    for csv_file, label in group_entries:
        if "name4" in label:
            shape_key = "name4"
        elif "name1" in label:
            shape_key = "name1"
        elif "name2" in label:
            shape_key = "name2"
        elif "name3" in label:
            shape_key = "name3"
        else:
            continue
        data_label = label.split(",")[0].strip()
        grouped[shape_key].append((data_label, csv_file))

    # === Sort keys for consistent subplot layout
    shape_keys = ["name1", "name2", "name3", "name4"]
    num_shapes = len(shape_keys)
    fig, axes = plt.subplots(1, num_shapes, figsize=(5 * num_shapes, 6), sharey=True)

    bar_width = 0.35
    color_map = {
        "Full Validation": "#4e79a7",
        "UpSHACL": "#59a14f"
    }

    for ax, shape_key in zip(axes, shape_keys):
        entries = grouped[shape_key]
        full_vals, upshacl_vals = [], []
        full_errs, upshacl_errs = [], []
        labels = []

        for data_label, csv_file in entries:
            df = pd.read_csv(os.path.join(CSV_FOLDER, csv_file))
            results_df = pd.read_csv(os.path.join(RESULTS_FOLDER, csv_file))
            df[TIMING_COLS['full_val']] = results_df[TIMING_COLS['full_val']]

            full_times = df[TIMING_COLS['shapes_load']] + df[TIMING_COLS['full_val']]
            upshacl_times = (
                df[TIMING_COLS['aff_pairs']] +
                df[TIMING_COLS['red_build']] +
                df[TIMING_COLS['ttl_load']] +
                df[TIMING_COLS['red_val']] +
                df[TIMING_COLS['shapes_load']]
            )

            full_mean = full_times.mean()
            upshacl_mean = upshacl_times.mean()
            full_min, full_max = full_times.min(), full_times.max()
            upshacl_min, upshacl_max = upshacl_times.min(), upshacl_times.max()

            full_vals.append(full_mean)
            upshacl_vals.append(upshacl_mean)

            full_errs.append([[full_mean - full_min], [full_max - full_mean]])
            upshacl_errs.append([[upshacl_mean - upshacl_min], [upshacl_max - upshacl_mean]])

            labels.append(data_label)

        x = np.arange(len(labels))
        full_errs = np.array(full_errs).squeeze().T
        upshacl_errs = np.array(upshacl_errs).squeeze().T

        bars1 = ax.bar(
            x - bar_width / 2,
            full_vals,
            width=bar_width,
            label="Full Validation",
            color=color_map["Full Validation"],
            yerr=full_errs,
            capsize=6,
            error_kw=dict(lw=1.5)
        )
        bars2 = ax.bar(
            x + bar_width / 2,
            upshacl_vals,
            width=bar_width,
            label="UpSHACL",
            color=color_map["UpSHACL"],
            yerr=upshacl_errs,
            capsize=6,
            error_kw=dict(lw=1.5)
        )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=TICK_SIZE)
        ax.set_title(shape_key, fontsize=LABEL_SIZE - 2, weight='bold', pad=10)
        ax.set_yscale('log')
        ax.set_ylim(y_limits)
        ax.tick_params(axis='y', labelsize=TICK_SIZE)
        ax.set_axisbelow(True)
        ax.grid(True, axis='y', which='both', linestyle='--', linewidth=1.0, alpha=0.8)

    axes[0].set_ylabel("Avg. Runtime (s)", fontsize=LABEL_SIZE)
    for ax in axes[1:]:
        ax.tick_params(labelleft=False)

    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.18, top=0.90, wspace=0.3)

    handles = [plt.Rectangle((0, 0), 1, 1, color=color_map["Full Validation"]),
               plt.Rectangle((0, 0), 1, 1, color=color_map["UpSHACL"])]
    labels = ["Full Validation", "UpSHACL"]

    fig.legend(
        handles, labels,
        loc='lower center',
        bbox_to_anchor=(0.5, -0.13),
        ncol=2,
        frameon=False,
        fontsize=LEGEND_SIZE
    )

    fig.savefig(os.path.join(OUTPUT_FOLDER, output_path), format='pdf', bbox_inches='tight')
    plt.close(fig)
    print(f"→ saved {output_path}")



def generate_comparison_legend(output_path):
    fig = plt.figure(figsize=(8, 1.5))
    fig.legend(
        legend_handles, legend_labels,
        loc='center', ncol=3, frameon=False,
        fontsize=LEGEND_SIZE, title="Method",
        title_fontsize=LEGEND_SIZE+2,
        handlelength=3.0, handletextpad=1.0,
        columnspacing=2.5
    )
    plt.axis('off')
    fig.tight_layout()
    fig.savefig(output_path, format='pdf', bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)
    print(f"→ saved legend {output_path}")

if __name__ == "__main__":
    plot_all_shapes_grouped(
        group_entries=groups["group1"] + groups["group2"],
        y_limits=global_limits,
        output_path="validation_grouped_by_shape.pdf"
    )

