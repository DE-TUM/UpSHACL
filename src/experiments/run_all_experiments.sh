#!/bin/bash

cd "$(dirname "$0")/.."

echo "Starting experiments: $(date)"

# Start 12 runners in parallel
for i in 0
do
    .venv/Scripts/python.exe -u -m src.run_experiments $i 1 > server_run_$i.log 2>&1 &
done

echo "Finished launching experiments: $(date)"
