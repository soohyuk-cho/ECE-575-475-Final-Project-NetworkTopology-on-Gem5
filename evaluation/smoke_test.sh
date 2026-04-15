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

    echo "=== Smoke Test: ${name} (${topo}, ${nodes} nodes) ==="
    if "$GEM5_BIN" --outdir "${OUTDIR}/${name}" "$SCRIPT" \
        --num-cpus="${nodes}" --num-dirs="${nodes}" --network=garnet \
        --topology="${topo}" --mesh-rows="${mesh_rows}" \
        --sim-cycles=1000 --synthetic=uniform_random --injectionrate=0.05 \
        > "${OUTDIR}/${name}_stdout.txt" 2>&1; then

        if grep -q "average_packet_latency" "${OUTDIR}/${name}/stats.txt" 2>/dev/null; then
            echo "  PASS: stats.txt contains network stats"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: stats.txt missing or incomplete"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "  FAIL: gem5 exited with error (see ${OUTDIR}/${name}_stdout.txt)"
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
