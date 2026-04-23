#!/usr/bin/env python3
"""
Topology visualizer for gem5 Garnet networks.

Reads config.json from a completed gem5 run and draws the router-level
network topology with layout appropriate for each topology type.

Usage:
    # Draw all topologies (picks one representative run per topology)
    python3 evaluation/draw_topology.py

    # Draw a specific topology from a specific run directory
    python3 evaluation/draw_topology.py --outdir evaluation/results/core_sweep/Mesh_XY/16nodes/uniform_random/inj_0.02

    # Override output format
    python3 evaluation/draw_topology.py --format png
"""

import argparse
import json
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

RESULTS_ROOT = Path(__file__).resolve().parent / "results" / "core_sweep"
PLOTS_DIR    = Path(__file__).resolve().parent / "plots" / "topology_diagrams"

ROUTER_COLOR  = "#0072B2"
LINK_COLOR    = "#888888"
LABEL_COLOR   = "white"
NODE_COLOR    = "#E69F00"   # external controller nodes (shown as small dots)

plt.rcParams.update({
    "font.size": 11,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "figure.facecolor": "white",
})


# ──────────────────────────────────────────────────────────────────────
# Config.json parsing
# ──────────────────────────────────────────────────────────────────────

def load_network(outdir: str) -> dict:
    """Load config.json and return the network sub-dict."""
    config_path = os.path.join(outdir, "config.json")
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"config.json not found in {outdir}")
    with open(config_path) as f:
        cfg = json.load(f)
    return cfg["system"]["ruby"]["network"]


def router_id_from_path(path: str) -> int:
    """Extract router id from a path like 'system.ruby.network.routers3' -> 3."""
    return int(path.split("routers")[-1])


def build_graph(network: dict):
    """Build a directed NetworkX graph from Garnet network config."""
    G = nx.DiGraph()

    for r in network["routers"]:
        G.add_node(r["router_id"])

    for link in network["int_links"]:
        src = router_id_from_path(link["src_node"])
        dst = router_id_from_path(link["dst_node"])
        G.add_edge(src, dst,
                   src_outport=link.get("src_outport", ""),
                   dst_inport=link.get("dst_inport", ""),
                   weight=link.get("weight", 1))

    return G


# ──────────────────────────────────────────────────────────────────────
# Layout detection and positioning
# ──────────────────────────────────────────────────────────────────────

def detect_topology_type(network: dict) -> str:
    """Infer topology from link port names."""
    ports = set()
    for link in network["int_links"]:
        ports.add(link.get("src_outport", ""))
        ports.add(link.get("dst_inport", ""))

    if "East" in ports or "West" in ports:
        return "mesh"
    if "CW" in ports or "CCW" in ports:
        return "ring"
    if len(network["routers"]) == 1:
        return "crossbar"
    # Pt2Pt: fully connected, no named ports
    return "fully_connected"


def mesh_layout(n_routers: int, mesh_rows: int) -> dict:
    """Grid layout for mesh topologies."""
    cols = n_routers // mesh_rows
    pos = {}
    for i in range(n_routers):
        row = i // cols
        col = i % cols
        pos[i] = (col, -row)   # y flipped so row 0 is at top
    return pos


def ring_layout(n_routers: int) -> dict:
    """Circular layout for ring topologies."""
    pos = {}
    for i in range(n_routers):
        angle = 2 * math.pi * i / n_routers - math.pi / 2
        pos[i] = (math.cos(angle), math.sin(angle))
    return pos


def crossbar_layout(n_routers: int) -> dict:
    return {0: (0.0, 0.0)}


def fc_layout(n_routers: int) -> dict:
    """Circular layout for fully-connected (Pt2Pt) topologies."""
    return ring_layout(n_routers)


def get_layout(G: nx.DiGraph, network: dict, topo_type: str,
               mesh_rows: int = None) -> dict:
    n = len(G.nodes)
    if topo_type == "mesh":
        rows = mesh_rows or max(1, int(math.isqrt(n)))
        return mesh_layout(n, rows)
    if topo_type == "ring":
        return ring_layout(n)
    if topo_type == "crossbar":
        return crossbar_layout(n)
    return fc_layout(n)


# ──────────────────────────────────────────────────────────────────────
# Drawing
# ──────────────────────────────────────────────────────────────────────

def draw_topology(network: dict, topology_name: str, nodes: int,
                  output_path: str, mesh_rows: int = None) -> None:
    G = build_graph(network)
    topo_type = detect_topology_type(network)
    pos = get_layout(G, network, topo_type, mesh_rows)

    n_routers = len(G.nodes)
    n_links   = len(network["int_links"])

    # Figure sizing: scale with node count
    fig_size = max(5, min(12, 2 + n_routers * 0.6))
    fig, ax = plt.subplots(figsize=(fig_size, fig_size * 0.85))

    # Draw edges — bidirectional pairs drawn as single lines with arrows
    # For clarity, use connectionstyle arc to separate bidirectional edges
    is_fully_connected = topo_type == "fully_connected"
    conn_style = "arc3,rad=0.0" if not is_fully_connected else "arc3,rad=0.15"

    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color=LINK_COLOR,
        width=1.8 if not is_fully_connected else 0.7,
        alpha=0.7,
        arrows=True,
        arrowsize=12 if not is_fully_connected else 6,
        arrowstyle="-|>",
        connectionstyle=conn_style,
        min_source_margin=18,
        min_target_margin=18,
    )

    # Draw routers as filled circles
    node_size = max(300, min(900, 3000 // n_routers))
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=ROUTER_COLOR,
        node_size=node_size,
        edgecolors="white",
        linewidths=1.5,
    )

    # Router ID labels
    font_size = max(7, min(11, 120 // n_routers))
    nx.draw_networkx_labels(
        G, pos, ax=ax,
        font_color=LABEL_COLOR,
        font_size=font_size,
        font_weight="bold",
    )

    # Port labels on edges for small graphs (skip for Pt2Pt — too cluttered)
    if n_routers <= 16 and not is_fully_connected:
        edge_labels = {}
        for u, v, data in G.edges(data=True):
            src_port = data.get("src_outport", "")
            if src_port:
                edge_labels[(u, v)] = src_port
        nx.draw_networkx_edge_labels(
            G, pos, edge_labels=edge_labels, ax=ax,
            font_size=6, font_color="#444444",
            bbox=dict(boxstyle="round,pad=0.1", fc="white", alpha=0.6, ec="none"),
        )

    # Legend / info box
    legend_patches = [
        mpatches.Patch(color=ROUTER_COLOR, label=f"Router (×{n_routers})"),
    ]
    ax.legend(handles=legend_patches, loc="upper right", fontsize=9,
              framealpha=0.85)

    topo_type_label = {
        "mesh": "2D Mesh",
        "ring": "Bidirectional Ring",
        "crossbar": "Crossbar (single router)",
        "fully_connected": "Fully Connected (Pt2Pt)",
    }.get(topo_type, topo_type)

    ax.set_title(
        f"{topology_name}   —   {nodes} nodes   |   "
        f"{n_routers} routers, {n_links} directed links\n"
        f"({topo_type_label})",
        fontsize=12, pad=10,
    )
    ax.axis("off")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    print(f"  Saved {output_path}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def find_representative_run(topology: str, nodes: int) -> str | None:
    """Find any completed run directory for (topology, nodes)."""
    base = RESULTS_ROOT / topology / f"{nodes}nodes"
    if not base.exists():
        return None
    for traffic_dir in base.iterdir():
        for inj_dir in sorted(traffic_dir.iterdir()):
            if (inj_dir / "config.json").exists():
                return str(inj_dir)
    return None


def infer_mesh_rows(topology: str, nodes: int) -> int:
    """Return mesh_rows for mesh topologies."""
    if "Mesh" not in topology:
        return 1
    r = int(math.isqrt(nodes))
    while r > 0 and nodes % r != 0:
        r -= 1
    return max(r, 1)


def main():
    parser = argparse.ArgumentParser(description="Visualize gem5 Garnet network topology")
    parser.add_argument("--outdir", default=None,
                        help="Specific gem5 run directory containing config.json")
    parser.add_argument("--topology", default=None,
                        help="Draw only this topology (from core_sweep results)")
    parser.add_argument("--nodes", type=int, default=16,
                        help="Node count to use when auto-finding runs (default: 16)")
    parser.add_argument("--format", default="png",
                        choices=["png", "pdf", "svg"],
                        help="Output image format")
    args = parser.parse_args()

    fmt = args.format

    if args.outdir:
        # Single explicit directory
        network = load_network(args.outdir)
        topo_name = Path(args.outdir).parts[-4] if len(Path(args.outdir).parts) >= 4 else "topology"
        nodes_str = Path(args.outdir).parts[-3] if len(Path(args.outdir).parts) >= 3 else "Nnodes"
        nodes = int("".join(filter(str.isdigit, nodes_str))) if nodes_str else args.nodes
        mesh_rows = infer_mesh_rows(topo_name, nodes)
        out_path = str(PLOTS_DIR / f"topo_{topo_name}_{nodes}nodes.{fmt}")
        draw_topology(network, topo_name, nodes, out_path, mesh_rows)
        return

    # Auto-discover topologies from core_sweep results
    if not RESULTS_ROOT.exists():
        print(f"No results found at {RESULTS_ROOT}. Run experiments first.")
        return

    topologies = (
        [args.topology] if args.topology
        else [d.name for d in sorted(RESULTS_ROOT.iterdir()) if d.is_dir()]
    )

    # Draw one diagram per (topology, node_count) to show how the topology scales
    node_counts = [args.nodes] if args.nodes != 16 else None

    print(f"Drawing topology diagrams -> {PLOTS_DIR}/")
    for topo in topologies:
        topo_dir = RESULTS_ROOT / topo
        if not topo_dir.exists():
            print(f"  SKIP: no results for {topo}")
            continue

        available_nodes = sorted(
            int(d.name.replace("nodes", ""))
            for d in topo_dir.iterdir()
            if d.is_dir() and d.name.endswith("nodes")
        )
        draw_nodes = node_counts or available_nodes

        for nodes in draw_nodes:
            run_dir = find_representative_run(topo, nodes)
            if run_dir is None:
                print(f"  SKIP: no completed run for {topo}/{nodes}nodes")
                continue
            try:
                network  = load_network(run_dir)
                mesh_rows = infer_mesh_rows(topo, nodes)
                out_path  = str(PLOTS_DIR / f"topo_{topo}_{nodes}nodes.{fmt}")
                draw_topology(network, topo, nodes, out_path, mesh_rows)
            except Exception as e:
                print(f"  ERROR {topo}/{nodes}nodes: {e}")


if __name__ == "__main__":
    main()
