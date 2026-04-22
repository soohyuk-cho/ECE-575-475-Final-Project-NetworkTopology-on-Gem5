# NoC Topology Evaluation Framework

Automated sweep, analysis, and plotting pipeline for comparing on-chip network topologies in gem5 Garnet.

Built for ECE 575/475 Final Project — Princeton University, Spring 2026.

---

## Overview

This framework evaluates network topologies under synthetic traffic using gem5's Garnet interconnect model. It sweeps across injection rates, node counts, and traffic patterns to produce latency/throughput curves, saturation comparisons, scalability trends, and latency decomposition plots.

**Topologies currently evaluated:**

| Topology | Description |
|---|---|
| `CrossbarGarnet` | Single shared router — ideal crossbar baseline |
| `Mesh_XY` | 2D mesh with deterministic XY routing |
| `Mesh_westfirst` | 2D mesh with west-first adaptive routing |
| `Ring` | Bidirectional ring, CW/CCW shortest-path routing |
| `Pt2Pt` | Fully connected — every node has a direct link to every other; upper-bound on bisection bandwidth |
| `Tree` | *(pending — not yet implemented)* |
| `Star` | *(pending — not yet implemented)* |

---

## Prerequisites

- gem5 built with the NULL ISA (`build/NULL/gem5.opt`)
- Python 3.9+
- Python packages: `pip3 install matplotlib pandas numpy`

Build gem5 if not already done:

```bash
./evaluation/build_gem5.sh
```

---

## Quick Start

```bash
# 1. Validate the build
./evaluation/smoke_test.sh

# 2. Run all experiments (resumes from prior progress automatically)
python3 evaluation/run_experiments.py

# 3. Parse stats into CSV
python3 evaluation/parse_stats.py

# 4. Generate all plots
python3 evaluation/plot_results.py --format png
```

---

## Scripts

### `build_gem5.sh`

Builds `build/NULL/gem5.opt`. Tees output to `evaluation/build.log`.

```bash
./evaluation/build_gem5.sh           # default: opt build, auto-detect CPU count
./evaluation/build_gem5.sh debug 4   # debug build, 4 jobs
```

---

### `smoke_test.sh`

Validates the gem5 build by running short simulations on CrossbarGarnet and Mesh_XY. Tests each available custom topology (Ring, Pt2Pt, etc.) and prints SKIP for missing ones.

```bash
./evaluation/smoke_test.sh
```

---

### `run_experiments.py`

Main orchestrator. Sweeps all (topology, nodes, traffic, injection rate) combinations in parallel and logs failures.

```bash
# Full sweep — skips already-completed runs
python3 evaluation/run_experiments.py

# Inspect commands without running
python3 evaluation/run_experiments.py --dry-run

# Single topology
python3 evaluation/run_experiments.py --topology Ring

# Filter by multiple dimensions
python3 evaluation/run_experiments.py --topology Mesh_XY --nodes 16 --traffic uniform_random

# Force re-run even if results exist
python3 evaluation/run_experiments.py --topology Pt2Pt --force

# Sensitivity study only (router latency + VC sweep)
python3 evaluation/run_experiments.py --sensitivity-only

# Core sweep only (skip sensitivity)
python3 evaluation/run_experiments.py --core-only

# Control parallelism
python3 evaluation/run_experiments.py --parallel 4
```

**Parameter space (core sweep):**

| Parameter | Values |
|---|---|
| Topologies | CrossbarGarnet, Mesh_XY, Mesh_westfirst, Ring, Pt2Pt |
| Node counts | 8, 16, 32 |
| Traffic patterns | uniform_random, neighbor, transpose, tornado |
| Injection rates | 0.02 – 0.50 (15 points) |
| sim_cycles | 100,000 |

**Sensitivity study** (Mesh_XY, 16 nodes, uniform_random):
- Router latency: 1–5 cycles
- VCs per vnet: 1, 2, 4, 8

Results are written to `evaluation/results/` (see structure below). Failed runs are logged to `evaluation/results/failed_runs.log`.

---

### `parse_stats.py`

Scans all `stats.txt` files under `evaluation/results/` and extracts gem5 Garnet metrics into two CSVs.

```bash
python3 evaluation/parse_stats.py
```

**Outputs:**
- `evaluation/results/all_results.csv` — one row per simulation run
- `evaluation/results/saturation_summary.csv` — saturation throughput per (topology, nodes, traffic)

**Metrics extracted:**

| Column | gem5 stat | Description |
|---|---|---|
| `avg_packet_latency` | `average_packet_latency` | End-to-end packet latency (ticks) |
| `avg_flit_latency` | `average_flit_latency` | Flit latency (ticks) |
| `avg_hops` | `average_hops` | Average router hops traversed |
| `packets_injected` | `packets_injected::total` | Total packets sent |
| `packets_received` | `packets_received::total` | Total packets delivered |
| `flits_received` | `flits_received::total` | Total flits delivered |
| `avg_flit_network_latency` | `average_flit_network_latency` | Router + link traversal time |
| `avg_flit_queueing_latency` | `average_flit_queueing_latency` | VC queueing delay |
| `int_link_util` | `int_link_utilization` | Internal link utilization |
| `ext_in_link_util` | `ext_in_link_utilization` | External input link utilization |
| `ext_out_link_util` | `ext_out_link_utilization` | External output link utilization |
| `throughput` | derived | `packets_received / sim_cycles` |
| `accepted_traffic` | derived | `flits_received / (sim_cycles × nodes)` — standard NoC metric |

---

### `plot_results.py`

Generates publication-quality plots from `all_results.csv`.

```bash
python3 evaluation/plot_results.py                          # PDF output (default)
python3 evaluation/plot_results.py --format png             # PNG output
python3 evaluation/plot_results.py --format png --csv path/to/custom.csv
```

**Output structure** under `evaluation/plots/`:

| Subdirectory | Contents | Count |
|---|---|---|
| `latency/` | Avg packet latency vs. injection rate, per (traffic, nodes) | 12+ |
| `throughput/` | Accepted traffic vs. injection rate, per (traffic, nodes) | 12+ |
| `saturation/` | Peak throughput & saturation injection rate bar charts | 6+ |
| `hops/` | Average hop count per topology, per node count | 3+ |
| `heatmaps/` | Topology × traffic peak throughput heatmap | 3+ |
| `sensitivity/` | Latency curves vs. router latency and VC count | 2 |
| `scalability/` | Latency vs. node count at moderate injection rate | 4 |
| `decomposition/` | Flit latency split: network component vs. VC queueing | 12+ |

> **Note:** Tornado and transpose traffic patterns compute destination addresses using mesh row/column geometry. Results for non-mesh topologies (Ring, Pt2Pt, CrossbarGarnet) under these patterns are marked with hatching in saturation plots — the traffic pattern does not exercise realistic non-mesh traffic distribution.

---

## Output Directory Structure

```
evaluation/
  results/
    core_sweep/
      {Topology}/
        {N}nodes/
          {traffic}/
            inj_{rate}/
              stats.txt
              simout.txt
    sensitivity/
      router_latency/
        rl_{val}/inj_{rate}/stats.txt
      vcs_per_vnet/
        vcs_{val}/inj_{rate}/stats.txt
    all_results.csv
    saturation_summary.csv
    failed_runs.log
  plots/
    latency/
    throughput/
    saturation/
    hops/
    heatmaps/
    sensitivity/
    scalability/
    decomposition/
```

---

## Adding a New Topology

1. Create `configs/topologies/{TopologyName}.py` extending `SimpleTopology`
2. Implement `makeTopology(options, network, IntLink, ExtLink, Router)` — assign link `weight` values on all `IntLink`s (required for deadlock-free routing in Garnet)
3. Implement `registerTopology(options)` calling `FileSystemConfig.register_node()`
4. Add the topology name to `CONFIG["topologies"]` in `run_experiments.py`
5. Add lowercase aliases to `TOPOLOGY_ALIASES` if desired
6. If the topology uses a mesh-like grid, add it to `MESH_TOPOLOGIES` so `--mesh-rows` is computed correctly

Run a smoke test before the full sweep:

```bash
build/NULL/gem5.opt --outdir /tmp/test \
  configs/example/garnet_synth_traffic.py \
  --num-cpus=8 --num-dirs=8 --network=garnet \
  --topology=TopologyName --mesh-rows=1 \
  --sim-cycles=100000 --synthetic=uniform_random --injectionrate=0.10 \
  --router-latency=1 --vcs-per-vnet=4
```

---

## Known Incompatible Topologies

| Topology | Reason |
|---|---|
| `Cluster` | Extends `BaseTopology` (not `SimpleTopology`); `__init__` signature incompatible with gem5's topology loader; must be composed manually inside a protocol's `create_system()` |
| `Crossbar` | Designed for `--network=simple`; use `CrossbarGarnet` instead |
| `CustomMesh` | Requires CHI protocol (`assert buildEnv["PROTOCOL"] == "CHI"`); our build uses NULL/MI_example |
| `MeshDirCorners_XY` | Hard-coded `assert len(dir_nodes) == 4`; incompatible with `--num-dirs=num_cpus` |
