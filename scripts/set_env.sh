#!/usr/bin/env bash

# Determine script directory regardless of symlinks
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Determine project root based on invocation location
if [[ "$(basename "$SCRIPT_DIR")" == "scripts" ]]; then
    export PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    export PROJECT_ROOT="$SCRIPT_DIR"
fi
