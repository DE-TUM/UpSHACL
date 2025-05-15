#!/bin/bash

cd "$(dirname "$0")/.."

echo "Starting experiments: $(date)"

# Start 12 runners in parallel
for i in 0 1 2 3 4 5 6 7 8 9 10 11
do
    .venv/Scripts/python.exe -u -m src.run_experiments $i 12 > server_run_$i.log 2>&1
done

echo "Finished launching experiments: $(date)"
