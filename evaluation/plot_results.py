#!/usr/bin/env python3
"""
Generate publication-quality plots from gem5 Garnet evaluation CSV.

Reads all_results.csv (produced by parse_stats.py) and generates:
  1. Latency vs. injection rate curves
  2. Throughput vs. injection rate curves
  3. Saturation point comparison bar charts
  4. Average hops bar charts
  5. Topology x traffic heatmaps
  6. Sensitivity study plots
  7. Scalability plots

Usage:
    python3 evaluation/plot_results.py
    python3 evaluation/plot_results.py --csv evaluation/results/all_results.csv --format png
"""

import argparse
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────
# Style
# ──────────────────────────────────────────────────────────────────────

COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
MARKERS = ["o", "s", "^", "D", "v", "P"]

plt.rcParams.update({
    "font.size": 12,
    "figure.figsize": (8, 5),
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def save_fig(fig, output_dir: str, name: str, fmt: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{name}.{fmt}")
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved {path}")


def get_core_data(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["sweep_type"] == "core"].copy()


# ──────────────────────────────────────────────────────────────────────
# Plot 1: Latency vs. Injection Rate
# ──────────────────────────────────────────────────────────────────────

def plot_latency_vs_injrate(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """One figure per (traffic, nodes). One line per topology."""
    print("Generating latency vs. injection rate plots...")
    core = get_core_data(df)

    for traffic in core["traffic"].unique():
        for nodes in sorted(core["nodes"].unique()):
            subset = core[(core["traffic"] == traffic) & (core["nodes"] == nodes)]
            if subset.empty:
                continue

            fig, ax = plt.subplots()
            topos = sorted(subset["topology"].unique())
            for i, topo in enumerate(topos):
                tdata = subset[subset["topology"] == topo].sort_values("injection_rate")
                valid = tdata.dropna(subset=["avg_packet_latency"])
                if valid.empty:
                    continue
                ax.plot(
                    valid["injection_rate"], valid["avg_packet_latency"],
                    color=COLORS[i % len(COLORS)],
                    marker=MARKERS[i % len(MARKERS)],
                    markersize=5, linewidth=1.5, label=topo,
                )

            ax.set_xlabel("Injection Rate (packets/cycle/node)")
            ax.set_ylabel("Average Packet Latency (ticks)")
            ax.set_title(f"Packet Latency - {traffic}, {nodes} nodes")
            ax.legend(fontsize=10)
            save_fig(fig, output_dir, f"latency_vs_injrate_{traffic}_{nodes}", fmt)


# ──────────────────────────────────────────────────────────────────────
# Plot 2: Throughput vs. Injection Rate
# ──────────────────────────────────────────────────────────────────────

def plot_throughput_vs_injrate(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """One figure per (traffic, nodes). Y = accepted_traffic."""
    print("Generating throughput vs. injection rate plots...")
    core = get_core_data(df)

    for traffic in core["traffic"].unique():
        for nodes in sorted(core["nodes"].unique()):
            subset = core[(core["traffic"] == traffic) & (core["nodes"] == nodes)]
            if subset.empty:
                continue

            fig, ax = plt.subplots()

            # Ideal throughput reference line (y = x)
            max_rate = subset["injection_rate"].max()
            ax.plot(
                [0, max_rate], [0, max_rate],
                color="gray", linestyle="--", linewidth=1, alpha=0.5, label="Ideal (y=x)",
            )

            topos = sorted(subset["topology"].unique())
            for i, topo in enumerate(topos):
                tdata = subset[subset["topology"] == topo].sort_values("injection_rate")
                valid = tdata.dropna(subset=["accepted_traffic"])
                if valid.empty:
                    continue
                ax.plot(
                    valid["injection_rate"], valid["accepted_traffic"],
                    color=COLORS[i % len(COLORS)],
                    marker=MARKERS[i % len(MARKERS)],
                    markersize=5, linewidth=1.5, label=topo,
                )

            ax.set_xlabel("Injection Rate (packets/cycle/node)")
            ax.set_ylabel("Accepted Traffic (flits/cycle/node)")
            ax.set_title(f"Throughput - {traffic}, {nodes} nodes")
            ax.legend(fontsize=10)
            save_fig(fig, output_dir, f"throughput_vs_injrate_{traffic}_{nodes}", fmt)


# ──────────────────────────────────────────────────────────────────────
# Plot 3: Saturation Point Comparison
# ──────────────────────────────────────────────────────────────────────

def find_saturation_rate(group: pd.DataFrame) -> float:
    """Find injection rate where latency exceeds 2x minimum."""
    valid = group.dropna(subset=["avg_packet_latency"])
    valid = valid[valid["avg_packet_latency"] > 0].sort_values("injection_rate")
    if len(valid) < 2:
        return float("nan")
    min_lat = valid["avg_packet_latency"].min()
    threshold = 2.0 * min_lat
    saturated = valid[valid["avg_packet_latency"] > threshold]
    if saturated.empty:
        return float("nan")
    return saturated["injection_rate"].iloc[0]


def plot_saturation_comparison(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """Grouped bar chart: X=topology, grouped by traffic, Y=saturation rate."""
    print("Generating saturation comparison plots...")
    core = get_core_data(df)

    for nodes in sorted(core["nodes"].unique()):
        node_data = core[core["nodes"] == nodes]
        topos = sorted(node_data["topology"].unique())
        traffics = sorted(node_data["traffic"].unique())

        sat_data = {}
        for topo in topos:
            for traffic in traffics:
                group = node_data[(node_data["topology"] == topo) & (node_data["traffic"] == traffic)]
                sat_data[(topo, traffic)] = find_saturation_rate(group)

        fig, ax = plt.subplots()
        n_topos = len(topos)
        n_traffic = len(traffics)
        bar_width = 0.8 / max(n_traffic, 1)
        x = np.arange(n_topos)

        for j, traffic in enumerate(traffics):
            vals = [sat_data.get((t, traffic), float("nan")) for t in topos]
            offset = (j - n_traffic / 2 + 0.5) * bar_width
            ax.bar(x + offset, vals, bar_width * 0.9,
                   color=COLORS[j % len(COLORS)], label=traffic)

        ax.set_xlabel("Topology")
        ax.set_ylabel("Saturation Injection Rate")
        ax.set_title(f"Saturation Point Comparison - {nodes} nodes")
        ax.set_xticks(x)
        ax.set_xticklabels(topos, rotation=30, ha="right")
        ax.legend(fontsize=9)
        save_fig(fig, output_dir, f"saturation_comparison_{nodes}", fmt)


# ──────────────────────────────────────────────────────────────────────
# Plot 4: Average Hops
# ──────────────────────────────────────────────────────────────────────

def plot_avg_hops(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """Bar chart of average hops at low injection rate (0.02)."""
    print("Generating average hops plots...")
    core = get_core_data(df)
    low_rate = core[core["injection_rate"] == core["injection_rate"].min()]

    for nodes in sorted(low_rate["nodes"].unique()):
        node_data = low_rate[low_rate["nodes"] == nodes]
        topos = sorted(node_data["topology"].unique())

        # Average across traffic patterns (hops is structural, should be similar)
        hop_vals = []
        for topo in topos:
            tdata = node_data[node_data["topology"] == topo]
            mean_hops = tdata["avg_hops"].mean()
            hop_vals.append(mean_hops)

        fig, ax = plt.subplots()
        x = np.arange(len(topos))
        bars = ax.bar(x, hop_vals, color=COLORS[:len(topos)], width=0.6)

        # Add value labels on bars
        for bar, val in zip(bars, hop_vals):
            if not math.isnan(val):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=10)

        ax.set_xlabel("Topology")
        ax.set_ylabel("Average Hops")
        ax.set_title(f"Average Hop Count - {nodes} nodes")
        ax.set_xticks(x)
        ax.set_xticklabels(topos, rotation=30, ha="right")
        save_fig(fig, output_dir, f"avg_hops_{nodes}", fmt)


# ──────────────────────────────────────────────────────────────────────
# Plot 5: Topology x Traffic Heatmap
# ──────────────────────────────────────────────────────────────────────

def plot_heatmap(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """Heatmap of saturation throughput: rows=topologies, cols=traffic."""
    print("Generating topology x traffic heatmaps...")
    core = get_core_data(df)

    for nodes in sorted(core["nodes"].unique()):
        node_data = core[core["nodes"] == nodes]
        topos = sorted(node_data["topology"].unique())
        traffics = sorted(node_data["traffic"].unique())

        # Build matrix: max accepted_traffic before saturation
        matrix = np.full((len(topos), len(traffics)), np.nan)
        for i, topo in enumerate(topos):
            for j, traffic in enumerate(traffics):
                group = node_data[
                    (node_data["topology"] == topo) & (node_data["traffic"] == traffic)
                ]
                valid = group.dropna(subset=["accepted_traffic"])
                if not valid.empty:
                    matrix[i, j] = valid["accepted_traffic"].max()

        fig, ax = plt.subplots(figsize=(8, max(4, len(topos) * 0.8)))
        im = ax.imshow(matrix, cmap="RdYlGn", aspect="auto")

        ax.set_xticks(range(len(traffics)))
        ax.set_xticklabels(traffics, rotation=30, ha="right")
        ax.set_yticks(range(len(topos)))
        ax.set_yticklabels(topos)

        # Annotate cells
        for i in range(len(topos)):
            for j in range(len(traffics)):
                val = matrix[i, j]
                if not np.isnan(val):
                    ax.text(j, i, f"{val:.4f}", ha="center", va="center", fontsize=9)

        fig.colorbar(im, ax=ax, label="Max Accepted Traffic (flits/cycle/node)")
        ax.set_title(f"Peak Throughput Heatmap - {nodes} nodes")
        save_fig(fig, output_dir, f"heatmap_throughput_{nodes}", fmt)


# ──────────────────────────────────────────────────────────────────────
# Plot 6: Sensitivity Study
# ──────────────────────────────────────────────────────────────────────

def plot_sensitivity(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """Latency curves for router latency and VCs-per-vnet sweeps."""
    print("Generating sensitivity study plots...")

    # Router latency
    rl_data = df[df["sweep_type"] == "sensitivity_router_latency"]
    if not rl_data.empty:
        fig, ax = plt.subplots()
        for i, rl in enumerate(sorted(rl_data["router_latency"].unique())):
            subset = rl_data[rl_data["router_latency"] == rl].sort_values("injection_rate")
            valid = subset.dropna(subset=["avg_packet_latency"])
            if valid.empty:
                continue
            ax.plot(
                valid["injection_rate"], valid["avg_packet_latency"],
                color=COLORS[i % len(COLORS)],
                marker=MARKERS[i % len(MARKERS)],
                markersize=5, linewidth=1.5, label=f"RL={int(rl)}",
            )
        ax.set_xlabel("Injection Rate (packets/cycle/node)")
        ax.set_ylabel("Average Packet Latency (ticks)")
        ax.set_title("Sensitivity: Router Latency (Mesh_XY, 16 nodes, uniform_random)")
        ax.legend(fontsize=10)
        save_fig(fig, output_dir, "sensitivity_router_latency", fmt)
    else:
        print("  No router latency sensitivity data found, skipping")

    # VCs per vnet
    vcs_data = df[df["sweep_type"] == "sensitivity_vcs"]
    if not vcs_data.empty:
        fig, ax = plt.subplots()
        for i, vcs in enumerate(sorted(vcs_data["vcs_per_vnet"].unique())):
            subset = vcs_data[vcs_data["vcs_per_vnet"] == vcs].sort_values("injection_rate")
            valid = subset.dropna(subset=["avg_packet_latency"])
            if valid.empty:
                continue
            ax.plot(
                valid["injection_rate"], valid["avg_packet_latency"],
                color=COLORS[i % len(COLORS)],
                marker=MARKERS[i % len(MARKERS)],
                markersize=5, linewidth=1.5, label=f"VCs={int(vcs)}",
            )
        ax.set_xlabel("Injection Rate (packets/cycle/node)")
        ax.set_ylabel("Average Packet Latency (ticks)")
        ax.set_title("Sensitivity: VCs per VNet (Mesh_XY, 16 nodes, uniform_random)")
        ax.legend(fontsize=10)
        save_fig(fig, output_dir, "sensitivity_vcs", fmt)
    else:
        print("  No VCs sensitivity data found, skipping")


# ──────────────────────────────────────────────────────────────────────
# Plot 7: Scalability
# ──────────────────────────────────────────────────────────────────────

def plot_scalability(df: pd.DataFrame, output_dir: str, fmt: str) -> None:
    """Latency at a moderate injection rate (0.10) vs. node count."""
    print("Generating scalability plots...")
    core = get_core_data(df)

    # Pick injection rate closest to 0.10
    target_rate = 0.10
    rates = sorted(core["injection_rate"].unique())
    closest_rate = min(rates, key=lambda r: abs(r - target_rate)) if rates else target_rate
    rate_data = core[core["injection_rate"] == closest_rate]

    for traffic in sorted(rate_data["traffic"].unique()):
        traffic_data = rate_data[rate_data["traffic"] == traffic]
        if traffic_data.empty:
            continue

        fig, ax = plt.subplots()
        topos = sorted(traffic_data["topology"].unique())

        for i, topo in enumerate(topos):
            tdata = traffic_data[traffic_data["topology"] == topo].sort_values("nodes")
            valid = tdata.dropna(subset=["avg_packet_latency"])
            if valid.empty:
                continue
            ax.plot(
                valid["nodes"], valid["avg_packet_latency"],
                color=COLORS[i % len(COLORS)],
                marker=MARKERS[i % len(MARKERS)],
                markersize=7, linewidth=1.5, label=topo,
            )

        ax.set_xlabel("Number of Nodes")
        ax.set_ylabel("Average Packet Latency (ticks)")
        ax.set_title(f"Scalability - {traffic} (inj_rate={closest_rate})")
        ax.set_xticks(sorted(core["nodes"].unique()))
        ax.legend(fontsize=10)
        save_fig(fig, output_dir, f"scalability_{traffic}", fmt)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    default_csv = str(Path(__file__).resolve().parent / "results" / "all_results.csv")
    default_output = str(Path(__file__).resolve().parent / "plots")

    parser = argparse.ArgumentParser(description="Plot gem5 Garnet evaluation results")
    parser.add_argument("--csv", default=default_csv, help="Input CSV path")
    parser.add_argument("--output-dir", default=default_output, help="Output directory for plots")
    parser.add_argument("--format", default="pdf", choices=["pdf", "png", "svg"], help="Plot format")
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"ERROR: CSV not found at {args.csv}")
        print("Run parse_stats.py first to generate it.")
        return

    df = pd.read_csv(args.csv)
    print(f"Loaded {len(df)} rows from {args.csv}")

    plot_latency_vs_injrate(df, args.output_dir, args.format)
    plot_throughput_vs_injrate(df, args.output_dir, args.format)
    plot_saturation_comparison(df, args.output_dir, args.format)
    plot_avg_hops(df, args.output_dir, args.format)
    plot_heatmap(df, args.output_dir, args.format)
    plot_sensitivity(df, args.output_dir, args.format)
    plot_scalability(df, args.output_dir, args.format)

    print(f"\nAll plots saved to {args.output_dir}/")


if __name__ == "__main__":
    main()
