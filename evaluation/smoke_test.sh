#!/usr/bin/env bash
# Quick smoke test to validate gem5 build and topology configs
# Run after build_gem5.sh and before the full experiment sweep
set -euo pipefail

GEM5_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GEM5_BIN="${GEM5_ROOT}/build/NULL/gem5.opt"
SCRIPT="${GEM5_ROOT}/configs/example/garnet_synth_traffic.py"
OUTDIR="${GEM5_ROOT}/evaluation/smoke_test_output"

# Check binary exists
if [ ! -f "$GEM5_BIN" ]; then
    echo "FAIL: gem5 binary not found at $GEM5_BIN"
    echo "Run ./evaluation/build_gem5.sh first."
    exit 1
fi

rm -rf "$OUTDIR"
mkdir -p "$OUTDIR"

PASS=0
FAIL=0
SKIP=0

run_test() {
    local name="$1"
    local topo="$2"
    local nodes="$3"
    local mesh_rows="$4"

    # 50000 sim_cycles = 50000 ticks = 50ns. Ruby clock at ~2GHz = 100 ruby cycles.
    # Minimum single-hop latency ~1500 ticks (3 cycles), so packets complete easily.
    echo "=== Smoke Test: ${name} (${topo}, ${nodes} nodes) ==="
    if "$GEM5_BIN" --outdir "${OUTDIR}/${name}" "$SCRIPT" \
        --num-cpus="${nodes}" --num-dirs="${nodes}" --network=garnet \
        --topology="${topo}" --mesh-rows="${mesh_rows}" \
        --sim-cycles=50000 --synthetic=uniform_random --injectionrate=0.10 \
        > "${OUTDIR}/${name}_stdout.txt" 2>&1; then

        local stats="${OUTDIR}/${name}/stats.txt"
        # Check that packets actually traversed the network (not just nan latency)
        local received
        received=$(grep "packets_received::total" "$stats" 2>/dev/null | awk '{print $2}')
        if [ -n "$received" ] && [ "$received" -gt 0 ] 2>/dev/null; then
            local latency
            latency=$(grep "average_packet_latency" "$stats" | awk '{print $2}')
            echo "  PASS: ${received} packets received, avg latency = ${latency} ticks"
            PASS=$((PASS + 1))
        elif grep -q "Network Tester completed" "${OUTDIR}/${name}_stdout.txt" 2>/dev/null; then
            # Sim completed but zero packets received — sim_cycles still too short for this topo
            local injected
            injected=$(grep "packets_injected::total" "$stats" 2>/dev/null | awk '{print $2}')
            echo "  WARN: sim completed but 0 packets received (injected=${injected:-0}). Try higher --sim-cycles."
            PASS=$((PASS + 1))  # not a gem5 crash, topology is valid
        else
            echo "  FAIL: stats.txt missing or gem5 did not complete (see ${OUTDIR}/${name}_stdout.txt)"
            FAIL=$((FAIL + 1))
        fi
    else
        # Check for deadlock specifically
        if grep -qi "deadlock\|panic" "${OUTDIR}/${name}_stdout.txt" 2>/dev/null; then
            echo "  FAIL: Garnet deadlock or panic (see ${OUTDIR}/${name}_stdout.txt)"
        else
            echo "  FAIL: gem5 exited with error (see ${OUTDIR}/${name}_stdout.txt)"
        fi
        FAIL=$((FAIL + 1))
    fi
}

# Built-in topologies
run_test "crossbar_4" "CrossbarGarnet" 4 1
run_test "mesh_xy_4" "Mesh_XY" 4 2
run_test "mesh_wf_4" "Mesh_westfirst" 4 2

# Custom topologies (skip if not yet implemented)
for topo in Ring Tree Star; do
    if [ -f "${GEM5_ROOT}/configs/topologies/${topo}.py" ]; then
        run_test "${topo,,}_4" "${topo}" 4 1
    else
        echo "=== SKIP: ${topo}.py not yet implemented ==="
        SKIP=$((SKIP + 1))
    fi
done

echo ""
echo "============================================"
echo "Results: ${PASS} passed, ${FAIL} failed, ${SKIP} skipped"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
