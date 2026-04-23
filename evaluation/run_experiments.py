#!/usr/bin/env python3
"""
Experiment orchestrator for gem5 Garnet network topology evaluation.

Sweeps across topologies, node counts, traffic patterns, and injection rates.
Supports parallel execution, resume, and dry-run mode.

Usage:
    python3 evaluation/run_experiments.py --dry-run          # inspect commands
    python3 evaluation/run_experiments.py --topology Mesh_XY # run one topology
    python3 evaluation/run_experiments.py                    # full sweep
"""

import argparse
import math
import os
import subprocess
import sys
import time
from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed,
)
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

GEM5_ROOT = Path(__file__).resolve().parent.parent

CONFIG = {
    "gem5_binary": str(GEM5_ROOT / "build" / "NULL" / "gem5.opt"),
    "script": str(
        GEM5_ROOT / "configs" / "example" / "garnet_synth_traffic.py"
    ),
    "topologies_dir": str(GEM5_ROOT / "configs" / "topologies"),
    "sim_cycles": 100_000,
    "results_root": str(GEM5_ROOT / "evaluation" / "results"),
    # Plots are written by plot_results.py into subdirectories under plots_root:
    #   latency/  throughput/  saturation/  hops/  heatmaps/
    #   sensitivity/  scalability/  decomposition/
    "plots_root": str(GEM5_ROOT / "evaluation" / "plots"),
    "topologies": [
        "CrossbarGarnet",
        "Mesh_XY",
        "Mesh_westfirst",
        "Ring",
        "Pt2Pt",
        "Tree",
        "Star",
    ],
    "node_counts": [8, 16, 32],
    "traffic_patterns": ["uniform_random", "neighbor", "transpose", "tornado"],
    "injection_rates": [
        0.02,
        0.04,
        0.06,
        0.08,
        0.10,
        0.12,
        0.14,
        0.16,
        0.18,
        0.20,
        0.25,
        0.30,
        0.35,
        0.40,
        0.50,
    ],
    # Sensitivity study: run on one topology/nodes/traffic combo
    "sensitivity": {
        "topology": "Mesh_XY",
        "nodes": 16,
        "traffic": "uniform_random",
        "router_latencies": [1, 2, 3, 4, 5],
        "vcs_per_vnet": [1, 2, 4, 8],
    },
    "max_parallel": 8,
}

MESH_TOPOLOGIES = {"Mesh_XY", "Mesh_westfirst"}

# Topologies that cannot be used directly via --topology= with Garnet synth traffic:
#   Cluster  - extends BaseTopology (not SimpleTopology); __init__ takes no 'controllers' arg;
#              must be composed manually inside a protocol's create_system()
#   Crossbar - designed for --network=simple, not garnet; use CrossbarGarnet instead
UNSUPPORTED_TOPOLOGIES = {"Cluster", "Crossbar"}

# Aliases: map shorthand/lowercase names to the exact class name gem5 expects.
# gem5 does a case-sensitive module import (topologies.<name>), so the name
# must exactly match the .py filename and class name.
TOPOLOGY_ALIASES = {
    "crossbar": "CrossbarGarnet",
    "crossbargarnet": "CrossbarGarnet",
    "mesh": "Mesh_XY",
    "mesh_xy": "Mesh_XY",
    "meshxy": "Mesh_XY",
    "mesh_westfirst": "Mesh_westfirst",
    "meshwestfirst": "Mesh_westfirst",
    "westfirst": "Mesh_westfirst",
    "ring": "Ring",
    "pt2pt": "Pt2Pt",
    "p2p": "Pt2Pt",
    "tree": "Tree",
    "star": "Star",
}


def resolve_topology(name: str) -> str:
    """Resolve a topology name or alias to the canonical gem5 class name."""
    return TOPOLOGY_ALIASES.get(name.lower(), name)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def get_mesh_rows(topology: str, num_cpus: int) -> int:
    """Return --mesh-rows value. Mesh topologies get a proper grid; others get 1."""
    if topology not in MESH_TOPOLOGIES:
        return 1
    # Find the largest r such that r*r <= num_cpus and num_cpus % r == 0
    r = int(math.isqrt(num_cpus))
    while r > 0 and num_cpus % r != 0:
        r -= 1
    return max(r, 1)


def topology_exists(topology: str) -> bool:
    """Return True if topology is usable with Garnet synth traffic.

    Checks both that the .py file exists and that the topology is not on
    the known-incompatible list (Cluster, Pt2Pt, Crossbar).
    """
    if topology in UNSUPPORTED_TOPOLOGIES:
        return False
    return os.path.isfile(
        os.path.join(CONFIG["topologies_dir"], f"{topology}.py")
    )


def run_is_complete(outdir: str) -> bool:
    """Check if a previous run completed with actual packet traffic.

    A run that completed but produced only nan stats (e.g., sim_cycles too
    short so zero packets traversed) is NOT considered complete — it should
    be re-run. We check for a non-zero packets_received::total value.
    """
    stats_file = os.path.join(outdir, "stats.txt")
    if not os.path.isfile(stats_file):
        return False
    try:
        with open(stats_file) as f:
            for line in f:
                if "packets_received::total" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            return int(parts[1]) > 0
                        except ValueError:
                            return False
        return False
    except OSError:
        return False


def build_command(
    topology: str,
    num_cpus: int,
    traffic: str,
    inj_rate: float,
    outdir: str,
    router_latency: int = 1,
    vcs_per_vnet: int = 4,
) -> list[str]:
    """Build the gem5 command line for a single simulation run."""
    return [
        CONFIG["gem5_binary"],
        "--outdir",
        outdir,
        CONFIG["script"],
        f"--num-cpus={num_cpus}",
        f"--num-dirs={num_cpus}",
        "--network=garnet",
        f"--topology={topology}",
        f"--mesh-rows={get_mesh_rows(topology, num_cpus)}",
        f"--sim-cycles={CONFIG['sim_cycles']}",
        f"--synthetic={traffic}",
        f"--injectionrate={inj_rate}",
        f"--router-latency={router_latency}",
        f"--vcs-per-vnet={vcs_per_vnet}",
    ]


def run_single(cmd: list[str], outdir: str) -> dict:
    """Execute a single gem5 run. Returns a result dict."""
    os.makedirs(outdir, exist_ok=True)
    stdout_file = os.path.join(outdir, "simout.txt")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,  # 10 minute timeout per run
        )
        elapsed = time.time() - start

        with open(stdout_file, "wb") as f:
            f.write(result.stdout)

        if result.returncode != 0:
            output_text = result.stdout.decode("utf-8", errors="replace")
            is_deadlock = "Deadlock" in output_text
            return {
                "status": "deadlock" if is_deadlock else "error",
                "outdir": outdir,
                "returncode": result.returncode,
                "elapsed": elapsed,
                "message": (
                    "Deadlock detected"
                    if is_deadlock
                    else f"Exit code {result.returncode}"
                ),
            }

        return {"status": "ok", "outdir": outdir, "elapsed": elapsed}

    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "outdir": outdir,
            "elapsed": 600,
            "message": "Timed out after 600s",
        }
    except Exception as e:
        return {
            "status": "error",
            "outdir": outdir,
            "elapsed": 0,
            "message": str(e),
        }


# ──────────────────────────────────────────────────────────────────────
# Job generation
# ──────────────────────────────────────────────────────────────────────


def generate_core_sweep_jobs(args) -> list[dict]:
    """Generate all (topology, nodes, traffic, injection_rate) jobs."""
    jobs = []
    topologies = (
        [resolve_topology(args.topology)]
        if args.topology
        else CONFIG["topologies"]
    )
    node_counts = [args.nodes] if args.nodes else CONFIG["node_counts"]
    traffic_patterns = (
        [args.traffic] if args.traffic else CONFIG["traffic_patterns"]
    )

    for topo in topologies:
        if topo in UNSUPPORTED_TOPOLOGIES:
            print(
                f"  SKIP: {topo} is not compatible with Garnet synth traffic (see UNSUPPORTED_TOPOLOGIES)"
            )
            continue
        if not topology_exists(topo):
            print(
                f"  SKIP: {topo}.py not found in configs/topologies/ (not yet implemented)"
            )
            continue
        for nodes in node_counts:
            for traffic in traffic_patterns:
                for inj_rate in CONFIG["injection_rates"]:
                    outdir = os.path.join(
                        CONFIG["results_root"],
                        "core_sweep",
                        topo,
                        f"{nodes}nodes",
                        traffic,
                        f"inj_{inj_rate}",
                    )
                    jobs.append(
                        {
                            "sweep_type": "core",
                            "topology": topo,
                            "nodes": nodes,
                            "traffic": traffic,
                            "inj_rate": inj_rate,
                            "router_latency": 1,
                            "vcs_per_vnet": 4,
                            "outdir": outdir,
                        }
                    )
    return jobs


def generate_sensitivity_jobs(args) -> list[dict]:
    """Generate sensitivity study jobs (router latency + VCs)."""
    jobs = []
    sens = CONFIG["sensitivity"]
    topo = sens["topology"]

    if not topology_exists(topo):
        print(f"  SKIP sensitivity: {topo}.py not found")
        return jobs

    # Router latency sweep
    for rl in sens["router_latencies"]:
        for inj_rate in CONFIG["injection_rates"]:
            outdir = os.path.join(
                CONFIG["results_root"],
                "sensitivity",
                "router_latency",
                f"rl_{rl}",
                f"inj_{inj_rate}",
            )
            jobs.append(
                {
                    "sweep_type": "sensitivity_router_latency",
                    "topology": topo,
                    "nodes": sens["nodes"],
                    "traffic": sens["traffic"],
                    "inj_rate": inj_rate,
                    "router_latency": rl,
                    "vcs_per_vnet": 4,
                    "outdir": outdir,
                }
            )

    # VCs per vnet sweep
    for vcs in sens["vcs_per_vnet"]:
        for inj_rate in CONFIG["injection_rates"]:
            outdir = os.path.join(
                CONFIG["results_root"],
                "sensitivity",
                "vcs_per_vnet",
                f"vcs_{vcs}",
                f"inj_{inj_rate}",
            )
            jobs.append(
                {
                    "sweep_type": "sensitivity_vcs",
                    "topology": topo,
                    "nodes": sens["nodes"],
                    "traffic": sens["traffic"],
                    "inj_rate": inj_rate,
                    "router_latency": 1,
                    "vcs_per_vnet": vcs,
                    "outdir": outdir,
                }
            )

    return jobs


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="gem5 Garnet topology evaluation sweep"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without running"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=CONFIG["max_parallel"],
        help="Max parallel gem5 processes",
    )
    parser.add_argument(
        "--topology", type=str, default=None, help="Run only this topology"
    )
    parser.add_argument(
        "--nodes", type=int, default=None, help="Run only this node count"
    )
    parser.add_argument(
        "--traffic",
        type=str,
        default=None,
        help="Run only this traffic pattern",
    )
    parser.add_argument(
        "--sensitivity-only",
        action="store_true",
        help="Run only sensitivity study",
    )
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Run only core sweep (no sensitivity)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-run even if results exist"
    )
    args = parser.parse_args()

    # Check gem5 binary
    if not args.dry_run and not os.path.isfile(CONFIG["gem5_binary"]):
        print(f"ERROR: gem5 binary not found at {CONFIG['gem5_binary']}")
        print("Run ./evaluation/build_gem5.sh first.")
        sys.exit(1)

    # Generate jobs
    jobs = []
    if not args.sensitivity_only:
        jobs.extend(generate_core_sweep_jobs(args))
    if not args.core_only:
        jobs.extend(generate_sensitivity_jobs(args))

    if not jobs:
        print("No jobs to run.")
        return

    # Filter completed runs (unless --force)
    if not args.force:
        pending = [j for j in jobs if not run_is_complete(j["outdir"])]
        skipped = len(jobs) - len(pending)
        if skipped > 0:
            print(
                f"Skipping {skipped} already-completed runs (use --force to re-run)"
            )
        jobs = pending

    if not jobs:
        print("All runs already complete.")
        return

    print(f"Total jobs: {len(jobs)} | Parallelism: {args.parallel}")

    # Dry run: just print commands
    if args.dry_run:
        for j in jobs:
            cmd = build_command(
                j["topology"],
                j["nodes"],
                j["traffic"],
                j["inj_rate"],
                j["outdir"],
                j["router_latency"],
                j["vcs_per_vnet"],
            )
            print(" ".join(cmd))
        print(f"\n({len(jobs)} commands total)")
        return

    # Create results directory
    os.makedirs(CONFIG["results_root"], exist_ok=True)
    fail_log = os.path.join(CONFIG["results_root"], "failed_runs.log")

    completed = 0
    failed = 0
    total = len(jobs)
    start_time = time.time()

    with ProcessPoolExecutor(max_workers=args.parallel) as executor:
        future_to_job = {}
        for j in jobs:
            cmd = build_command(
                j["topology"],
                j["nodes"],
                j["traffic"],
                j["inj_rate"],
                j["outdir"],
                j["router_latency"],
                j["vcs_per_vnet"],
            )
            future = executor.submit(run_single, cmd, j["outdir"])
            future_to_job[future] = j

        for future in as_completed(future_to_job):
            j = future_to_job[future]
            result = future.result()
            completed += 1

            label = f"{j['topology']}/{j['nodes']}nodes/{j['traffic']}/inj={j['inj_rate']}"
            if result["status"] == "ok":
                print(
                    f"  [{completed}/{total}] OK  {label}  ({result['elapsed']:.1f}s)"
                )
            else:
                failed += 1
                msg = result.get("message", "unknown error")
                print(f"  [{completed}/{total}] FAIL {label}  ({msg})")
                with open(fail_log, "a") as f:
                    cmd = build_command(
                        j["topology"],
                        j["nodes"],
                        j["traffic"],
                        j["inj_rate"],
                        j["outdir"],
                        j["router_latency"],
                        j["vcs_per_vnet"],
                    )
                    f.write(f"{result['status']}: {' '.join(cmd)}\n")

    elapsed = time.time() - start_time
    print(
        f"\nDone: {total - failed} succeeded, {failed} failed, {elapsed:.1f}s total"
    )
    if failed > 0:
        print(f"See {fail_log} for details")


if __name__ == "__main__":
    main()
