#!/usr/bin/env python3
"""
Parse gem5 Garnet stats.txt files and produce consolidated CSVs.

Walks the results directory tree, extracts network metrics from each
stats.txt, and outputs:
  - all_results.csv        (one row per simulation run)
  - saturation_summary.csv (saturation point per topology/nodes/traffic)

Usage:
    python3 evaluation/parse_stats.py
    python3 evaluation/parse_stats.py --results-dir evaluation/results --output evaluation/results/all_results.csv
"""

import argparse
import csv
import math
import os
import re
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# Stat keys to extract from stats.txt
# ──────────────────────────────────────────────────────────────────────

SCALAR_STATS = {
    "system.ruby.network.average_packet_latency": "avg_packet_latency",
    "system.ruby.network.average_flit_latency": "avg_flit_latency",
    "system.ruby.network.average_hops": "avg_hops",
    "system.ruby.network.packets_injected::total": "packets_injected",
    "system.ruby.network.packets_received::total": "packets_received",
    "system.ruby.network.flits_received::total": "flits_received",
    "system.ruby.network.average_flit_network_latency": "avg_flit_network_latency",
    "system.ruby.network.average_flit_queueing_latency": "avg_flit_queueing_latency",
    "system.ruby.network.int_link_utilization": "int_link_util",
    "system.ruby.network.ext_in_link_utilization": "ext_in_link_util",
    "system.ruby.network.ext_out_link_utilization": "ext_out_link_util",
    "system.ruby.network.flits_injected::total": "flits_injected",
}

# Stats that have per-vnet pipe-separated values
PIPE_STATS = {
    "system.ruby.network.flit_network_latency": "flit_net_lat",
    "system.ruby.network.flit_queueing_latency": "flit_queue_lat",
}

CSV_COLUMNS = [
    "sweep_type", "topology", "nodes", "traffic", "injection_rate",
    "router_latency", "vcs_per_vnet",
    # Scalar metrics
    "avg_packet_latency", "avg_flit_latency", "avg_hops",
    "packets_injected", "packets_received",
    "flits_injected", "flits_received",
    "avg_flit_network_latency", "avg_flit_queueing_latency",
    "int_link_util", "ext_in_link_util", "ext_out_link_util",
    # Derived
    "throughput", "accepted_traffic",
    # Per-vnet (5 vnets each)
    "flit_net_lat_v0", "flit_net_lat_v1", "flit_net_lat_v2",
    "flit_net_lat_v3", "flit_net_lat_v4",
    "flit_queue_lat_v0", "flit_queue_lat_v1", "flit_queue_lat_v2",
    "flit_queue_lat_v3", "flit_queue_lat_v4",
]


# ──────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────

def parse_value(s: str) -> float:
    """Parse a stat value string, handling nan and inf."""
    s = s.strip()
    if s in ("nan", "inf", "-inf", ""):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_stats_file(filepath: str) -> dict:
    """Parse a gem5 stats.txt file and return a dict of extracted metrics."""
    metrics = {}

    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
    except OSError:
        return metrics

    for line in lines:
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("#"):
            continue

        # Check pipe-separated stats first
        matched_pipe = False
        for stat_key, col_prefix in PIPE_STATS.items():
            if line.startswith(stat_key) and "|" in line:
                # Format: stat_name | val0 | val1 | val2 | val3 | val4 (unit)
                # Strip the stat name and any trailing description
                rest = line[len(stat_key):]
                # Remove trailing (Unspecified) or similar
                rest = re.sub(r'\(.*?\)\s*$', '', rest)
                parts = [p.strip() for p in rest.split("|") if p.strip()]
                for i, val_str in enumerate(parts[:5]):
                    metrics[f"{col_prefix}_v{i}"] = parse_value(val_str)
                matched_pipe = True
                break

        if matched_pipe:
            continue

        # Check scalar stats
        for stat_key, col_name in SCALAR_STATS.items():
            if line.startswith(stat_key):
                # Format: stat_name    value    # description
                parts = line.split()
                if len(parts) >= 2:
                    metrics[col_name] = parse_value(parts[1])
                break

    return metrics


def extract_metadata_from_path(stats_path: str, results_root: str) -> dict:
    """Extract experiment parameters from the directory structure."""
    rel = os.path.relpath(os.path.dirname(stats_path), results_root)
    parts = Path(rel).parts

    meta = {
        "sweep_type": "",
        "topology": "",
        "nodes": 0,
        "traffic": "",
        "injection_rate": 0.0,
        "router_latency": 1,
        "vcs_per_vnet": 4,
    }

    if len(parts) < 2:
        return meta

    # core_sweep/{topology}/{nodes}nodes/{traffic}/inj_{rate}
    if parts[0] == "core_sweep" and len(parts) >= 5:
        meta["sweep_type"] = "core"
        meta["topology"] = parts[1]
        meta["nodes"] = int(parts[2].replace("nodes", ""))
        meta["traffic"] = parts[3]
        meta["injection_rate"] = float(parts[4].replace("inj_", ""))

    # sensitivity/router_latency/rl_{val}/inj_{rate}
    elif parts[0] == "sensitivity" and parts[1] == "router_latency" and len(parts) >= 4:
        meta["sweep_type"] = "sensitivity_router_latency"
        meta["topology"] = "Mesh_XY"
        meta["nodes"] = 16
        meta["traffic"] = "uniform_random"
        meta["router_latency"] = int(parts[2].replace("rl_", ""))
        meta["injection_rate"] = float(parts[3].replace("inj_", ""))

    # sensitivity/vcs_per_vnet/vcs_{val}/inj_{rate}
    elif parts[0] == "sensitivity" and parts[1] == "vcs_per_vnet" and len(parts) >= 4:
        meta["sweep_type"] = "sensitivity_vcs"
        meta["topology"] = "Mesh_XY"
        meta["nodes"] = 16
        meta["traffic"] = "uniform_random"
        meta["vcs_per_vnet"] = int(parts[2].replace("vcs_", ""))
        meta["injection_rate"] = float(parts[3].replace("inj_", ""))

    return meta


# ──────────────────────────────────────────────────────────────────────
# CSV output
# ──────────────────────────────────────────────────────────────────────

def compute_derived(row: dict, sim_cycles: int) -> None:
    """Compute throughput and accepted_traffic in-place."""
    pkts = row.get("packets_received", float("nan"))
    flits = row.get("flits_received", float("nan"))
    nodes = row.get("nodes", 1)

    if not math.isnan(pkts) and sim_cycles > 0:
        row["throughput"] = pkts / sim_cycles
    else:
        row["throughput"] = float("nan")

    if not math.isnan(flits) and sim_cycles > 0 and nodes > 0:
        row["accepted_traffic"] = flits / (sim_cycles * nodes)
    else:
        row["accepted_traffic"] = float("nan")


def find_saturation_point(rows: list[dict]) -> float:
    """Find the injection rate where latency exceeds 2x the minimum."""
    # Sort by injection rate
    sorted_rows = sorted(rows, key=lambda r: r.get("injection_rate", 0))

    # Find minimum latency (should be at low injection rates)
    latencies = [
        (r["injection_rate"], r.get("avg_packet_latency", float("nan")))
        for r in sorted_rows
    ]
    valid = [(rate, lat) for rate, lat in latencies if not math.isnan(lat) and lat > 0]

    if len(valid) < 2:
        return float("nan")

    min_lat = min(lat for _, lat in valid)
    threshold = 2.0 * min_lat

    for rate, lat in valid:
        if lat > threshold:
            return rate

    return float("nan")  # Never saturated within sweep range


def collect_and_write(results_root: str, output_csv: str, sim_cycles: int) -> None:
    """Walk results tree, parse all stats.txt, write CSVs."""
    rows = []

    for dirpath, _dirnames, filenames in os.walk(results_root):
        if "stats.txt" not in filenames:
            continue
        stats_path = os.path.join(dirpath, "stats.txt")
        meta = extract_metadata_from_path(stats_path, results_root)
        if not meta["sweep_type"]:
            continue

        metrics = parse_stats_file(stats_path)
        row = {**meta, **metrics}
        compute_derived(row, sim_cycles)
        rows.append(row)

    if not rows:
        print("No results found.")
        return

    # Sort for readability
    rows.sort(key=lambda r: (
        r["sweep_type"], r["topology"], r["nodes"],
        r["traffic"], r["injection_rate"],
    ))

    # Write main CSV
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Format nan as empty string
            formatted = {}
            for col in CSV_COLUMNS:
                val = row.get(col, "")
                if isinstance(val, float) and math.isnan(val):
                    formatted[col] = ""
                else:
                    formatted[col] = val
            writer.writerow(formatted)

    print(f"Wrote {len(rows)} rows to {output_csv}")

    # Write saturation summary
    sat_csv = output_csv.replace("all_results", "saturation_summary")
    if sat_csv == output_csv:
        sat_csv = output_csv.replace(".csv", "_saturation.csv")

    # Group core sweep rows by (topology, nodes, traffic)
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        if r["sweep_type"] == "core":
            key = (r["topology"], r["nodes"], r["traffic"])
            groups[key].append(r)

    sat_rows = []
    for (topo, nodes, traffic) in sorted(groups.keys()):
        sat_rate = find_saturation_point(groups[(topo, nodes, traffic)])
        sat_rows.append({
            "topology": topo,
            "nodes": nodes,
            "traffic": traffic,
            "saturation_injection_rate": sat_rate if not math.isnan(sat_rate) else "",
        })

    if sat_rows:
        with open(sat_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["topology", "nodes", "traffic", "saturation_injection_rate"]
            )
            writer.writeheader()
            writer.writerows(sat_rows)
        print(f"Wrote {len(sat_rows)} rows to {sat_csv}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    default_root = str(Path(__file__).resolve().parent / "results")

    parser = argparse.ArgumentParser(description="Parse gem5 Garnet stats into CSV")
    parser.add_argument("--results-dir", default=default_root, help="Path to results root")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument("--sim-cycles", type=int, default=100_000, help="Simulation cycles (for throughput calc)")
    args = parser.parse_args()

    output = args.output or os.path.join(args.results_dir, "all_results.csv")
    collect_and_write(args.results_dir, output, args.sim_cycles)


if __name__ == "__main__":
    main()
