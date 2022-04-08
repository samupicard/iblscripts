#!/bin/bash

# Make sure local pykilosort repository is up to date
cd ~/Documents/PYTHON/SPIKE_SORTING/pykilosort
git checkout -f ibl_prod -q
git reset --hard -q
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse "@{u}")
if [ $LOCAL != $REMOTE ]; then
  echo "Updating pykilosort"
  git pull
else
  echo "pykilosort is up-to-date"
fi

# Check that all libraries in the env are up to date
source ~/anaconda3/etc/profile.d/conda.sh
conda deactivate
conda activate pyks2

outdated=$(pip list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1)
for lib in "ibllib" "phylib"
do
  update=$(echo $outdated | grep $lib | cut -d = -f 1)
  if test "$update" ; then echo "Updating $lib" ; pip install -U $lib ; else echo "$lib is up-to-date" ; fi
done
conda deactivate
