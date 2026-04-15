#!/usr/bin/env bash
# Build gem5 for NULL ISA with Garnet support
# Usage: ./evaluation/build_gem5.sh [opt|debug] [num_jobs]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GEM5_ROOT="$(dirname "$SCRIPT_DIR")"

BUILD_TYPE="${1:-opt}"        # "opt" for performance, "debug" for debugging
NUM_JOBS="${2:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)}"

if [[ "$BUILD_TYPE" != "opt" && "$BUILD_TYPE" != "debug" ]]; then
    echo "Usage: $0 [opt|debug] [num_jobs]"
    echo "  opt   - optimized build (faster, use for experiment sweeps)"
    echo "  debug - debug build (slower, use for topology debugging)"
    exit 1
fi

cd "$GEM5_ROOT"

echo "============================================"
echo "Building gem5 NULL ISA (Garnet standalone)"
echo "  Build type: ${BUILD_TYPE}"
echo "  Parallel jobs: ${NUM_JOBS}"
echo "  Target: build/NULL/gem5.${BUILD_TYPE}"
echo "============================================"

scons "build/NULL/gem5.${BUILD_TYPE}" -j"${NUM_JOBS}" 2>&1 | tee "${SCRIPT_DIR}/build.log"

echo ""
echo "Build complete: build/NULL/gem5.${BUILD_TYPE}"
