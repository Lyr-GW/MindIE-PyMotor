#!/bin/bash
set -euo pipefail

# This script builds the motor wheel package.

# Allow verbosity control: set VERBOSE=1 to see full logs.
VERBOSE=${VERBOSE:-0}

# Clean up any existing build artifacts that might cause import issues.
rm -rf build/
rm -rf motor.egg-info/
rm -rf dist/

echo "Generating protobuf files..."
./scripts/generate_proto.sh

echo "Building wheel package with pip wheel (PEP517)... (VERBOSE=${VERBOSE})"

# Use pep517 build interface to avoid legacy setup.py warning.
cmd=(python -m pip wheel . --no-deps --use-pep517 -w dist)
if [[ "${VERBOSE}" -eq 0 ]]; then
  cmd+=(-q) # quiet output by default
fi

"${cmd[@]}"
