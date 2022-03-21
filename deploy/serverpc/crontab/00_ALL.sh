#!/bin/bash
cd ~/Documents/PYTHON/iblscripts/deploy/serverpc/crontab
source ~/Documents/PYTHON/envs/iblenv/bin/activate

# Update ibllib, iblscripts, etc. and use canary branch if canary_branch file present
./update_ibllib.sh
# Update DLC environment also now as it can otherwise lead to running DLC on partially installed env
echo "Updating DLC environment"
../dlc/update_dlcenv.sh

# Kill any currently running session create jobs
python jobs.py kill create
# Find the extract_me flags, create sessio on Alyx (if not present), register raw data and
# create task pipeline on Alyx
python jobs.py create /mnt/s0/Data/Subjects &

# Kill any small tasks that are still running
python jobs.py kill run_small
# Run small jobs (e.g. task extraction) that are set to Waiting in Alyx
python jobs.py run_small /mnt/s0/Data/Subjects &

# Run large jobs (e.g. spike sorting, DLC) that are set to Waiting in Alyx
# this doesn't require killing as existence of the process is checked in the python code
python jobs.py run_large /mnt/s0/Data/Subjects &

# Restart the report process (updates Alyx with diagnostic info every 2 hours)
python jobs.py kill report
python jobs.py report &

echo "Updating Spike Sorting environment"
../kilosort2/update_pykilosort.sh

# Search for aberrant data (misplaced data, sessions with wrong flags) and correct them
python maintenance.py
