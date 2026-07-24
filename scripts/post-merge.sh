#!/bin/bash
set -e

# Install/sync Python dependencies after a task merge
if [ -f requirements.txt ]; then
    pip install -q -r requirements.txt
fi
