import matplotlib.pyplot as plt
import pandas as pd
import os

# === Group mapping ===
groups = {
    "group1": [
        ("EnDe50_shapes30.csv",   "DB50, Shapes30"),
        ("EnDe100_shapes30.csv",  "DB100, Shapes30"),
        ("EnDe1000_shapes30.csv", "DB1000, Shapes30"),
        ("skg1_schema1.csv",      "SKG1, schema1"),
        ("skg1_schema2.csv",      "SKG1, schema2"),
        ("skg1_schema3.csv",      "SKG1, schema3"),
    ],
    "group2": [
        ("mkg1_schema1.csv", "MKG1, schema1"),
        ("mkg1_schema2.csv", "MKG1, schema2"),
        ("mkg1_schema3.csv", "MKG1, schema3"),
        ("lkg1_schema1.csv", "LKG1, schema1"),
        ("lkg1_schema2.csv", "LKG1, schema2"),
        ("lkg1_schema3.csv", "LKG1, schema3"),
    ]
}

# === Shared constants & styling ===
LABEL_SIZE = 28
TICK_SIZE  = 24
RUNTIME_COMPONENTS = {
    'timing_Affected pairs computation':  'Compute Affected Pairs',
    'timing_Reduced graphs building':     'Build Reduced Graph',
    'timing_Load reduced graph from ttl': 'Export Reduced Graph',
}
csv_folder    = "fresh_results"
output_folder = "composite_outputs_fresh"
os.makedirs(output_folder, exist_ok=True)

def get_runtime_df(csv_file):
    df = pd.read_csv(os.path.join(csv_folder, csv_file))
    df['run_label'] = [f"t{i+1}" for i in range(len(df))]
    runtime_df = df[['run_label'] + list(RUNTIME_COMPONENTS.keys())].copy()
    runtime_df.rename(columns=RUNTIME_COMPONENTS, inplace=True)
    runtime_df.set_index('run_label', inplace=True)
    runtime_df.index.name = None
    return runtime_df

# === Compute global y‐limits across all CSVs ===
all_mins = []
all_maxs = []

for group_entries in groups.values():
    for csv_file, _ in group_entries:
        df = get_runtime_df(csv_file)
        vals = df.values.flatten()
        positive = vals[vals > 0]
        if positive.size:
            all_mins.append(positive.min())
        all_maxs.append(vals.max())

y_min = min(all_mins)
y_max = max(all_maxs)

# pad in log‐space
y_range       = y_max / y_min
y_min_padded  = y_min / (y_range ** 0.05)
y_max_padded  = y_max * (y_range ** 0.05)

# clamp lower bound to 10^0 = 1
global_limits = (1.0, y_max_padded)

from collections import defaultdict

def group_by_shape():
    shape_groups = defaultdict(list)
    for group_entries in groups.values():
        for csv_file, label in group_entries:
            if "Shapes30" in label:
                shape_key = "Shapes30"
                data_label = label.split(",")[0].strip()
            elif "schema1" in label:
                shape_key = "schema1"
                data_label = label.split(",")[0].strip()
            elif "schema2" in label:
                shape_key = "schema2"
                data_label = label.split(",")[0].strip()
            elif "schema3" in label:
                shape_key = "schema3"
                data_label = label.split(",")[0].strip()
            else:
                continue
            shape_groups[shape_key].append((csv_file, data_label))
    return shape_groups

def plot_all_shapes_in_row(shape_groups, y_limits):
    import matplotlib.pyplot as plt
    import numpy as np

    # plt.style.use('seaborn-v0_8-muted')
    fig, axes = plt.subplots(1, 4, figsize=(20, 6), sharey=True)

    colors = {
        'Compute Affected Pairs':      '#4e79a7',
        'Build Reduced Graph':      '#59a14f',
        'Export Reduced Graph':   '#e15759',
    }

    runtime_components = list(RUNTIME_COMPONENTS.values())
    legend_handles = []
    legend_labels = []

    for ax, shape_key in zip(axes, ["schema1", "schema2", "schema3", "Shapes30"]):
        datasets = shape_groups[shape_key]
        avg_dfs = []
        data_labels = []

        for csv_file, short_label in datasets:
            df = get_runtime_df(csv_file)
            for col in runtime_components:
                if col not in df.columns:
                    df[col] = 0.0
            df = df[runtime_components]

            avg_df = df.mean(axis=0).to_frame().T
            avg_dfs.append(avg_df)
            data_labels.append(short_label)

        if not avg_dfs:
            continue

        full_df = pd.concat(avg_dfs, ignore_index=True)
        full_df.index = data_labels
        full_df = full_df.clip(lower=1.05)

        bar_width = 0.25
        num_components = len(runtime_components)
        x = np.arange(len(full_df.index))

        for i, col in enumerate(full_df.columns):
            bars = ax.bar(
                x + i * bar_width,
                full_df[col].values,
                width=bar_width,
                label=col,
                color=colors.get(col),
                zorder=2
            )
            if len(legend_handles) < len(runtime_components):
                legend_handles.append(bars[0])
                legend_labels.append(col)

        ax.set_xticks(x + bar_width * (num_components - 1) / 2)
        ax.set_xticklabels(full_df.index, fontsize=TICK_SIZE)

        ax.set_yscale('log')
        ax.set_ylim(y_limits)
        ax.set_title(shape_key, fontsize=LABEL_SIZE - 2, pad=10, weight='bold')
        ax.tick_params(axis='x', labelsize=TICK_SIZE, rotation=0)
        ax.tick_params(axis='y', labelsize=TICK_SIZE)
        ax.set_axisbelow(True)
        ax.grid(True, axis='y', which='both', linestyle='--', alpha=0.8, linewidth=1.0)

    axes[0].set_ylabel("Runtime (s)", fontsize=LABEL_SIZE)
    for ax in axes[1:]:
        ax.tick_params(labelleft=False)

    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.08, top=0.9, wspace=0.15)

    fig.legend(
        legend_handles,
        legend_labels,
        loc='lower center',
        bbox_to_anchor=(0.5, -0.15),
        ncol=len(legend_labels),
        frameon=False,
        fontsize=TICK_SIZE-2,
        handlelength=2.5,
        handletextpad=0.8,
        columnspacing=2.0
    )

    fig.savefig(
        os.path.join(output_folder, "composite_runtime_all_shapes_row.pdf"),
        format='pdf',
        bbox_inches='tight'
    )

    plt.close(fig)
    print("Saved: composite_runtime_all_shapes_row.pdf")





def plot_group_by_shape(shape_key, datasets, y_limits):
    plt.style.use('seaborn-v0_8-muted')
    n = len(datasets)
    fig, ax = plt.subplots(1, 1, figsize=(4 * n, 6))

    avg_dfs = []
    data_labels = []

    for csv_file, short_label in datasets:
        df = get_runtime_df(csv_file)
        avg_df = df.mean(axis=0).to_frame().T  # one row, average over t1-t3
        avg_dfs.append(avg_df)
        data_labels.append(short_label)

    full_df = pd.concat(avg_dfs, ignore_index=True)
    full_df.index = data_labels

    full_df.plot(kind='bar', stacked=True, ax=ax, width=0.7,
                 legend=True, zorder=2)

    ax.set_yscale('log')
    ax.set_ylim(y_limits)
    ax.set_title(f"UpSHACL Runtime Breakdown – {shape_key}", fontsize=LABEL_SIZE, pad=10, weight='bold')
    ax.set_xlabel("Data Graph", fontsize=LABEL_SIZE)
    ax.set_ylabel("Runtime (s)", fontsize=LABEL_SIZE)
    ax.tick_params(axis='x', labelsize=TICK_SIZE, rotation=0)
    ax.tick_params(axis='y', labelsize=TICK_SIZE)
    ax.set_axisbelow(True)
    ax.grid(True, axis='y', which='both', linestyle='--', alpha=0.9, zorder=1)

    fig.subplots_adjust(left=0.1, right=0.98, bottom=0.15, top=0.9)
    filename = f"breakdown_{shape_key}.pdf"
    fig.savefig(os.path.join(output_folder, filename), format='pdf')
    plt.close(fig)
    print("Saved:", filename)

# === Run plotting for all shape groups in your preferred order ===
ordered_shape_keys = ["schema1", "schema2", "schema3", "Shapes30"]
shape_groups = group_by_shape()
plot_all_shapes_in_row(shape_groups, global_limits)


