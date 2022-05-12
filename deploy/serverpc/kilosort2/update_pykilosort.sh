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
pip uninstall ibllib  # pykilosort 1.3.0 does not rely on ibllib anymore, just ibl-neuropixel
pip install ibl-neuropixel  # this is a one off and can be removed from June 2022 onwards. It is probably inocuous as fast anyway
outdated=$(pip list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1)

# Libraries that have to be updated in order
update=$(echo $outdated | grep -o "phylib" | cut -d = -f 1)
if test "$update" ; then
  echo "Updating phylib and ibl-neuropixel" ;
  pip uninstall -y ibl-neuropixel phylib ;
  pip install phylib ;
  pip install ibl-neuropixel ;
else
  echo "phylib is up-to-date" ;
  update=$(echo $outdated | grep -o "ibl-neuropixel" | cut -d = -f 1)
  if test "$update" ; then
    echo "Updating ibl-neuropixel" ;
    pip uninstall -y ibl-neuropixel ;
    pip install ibl-neuropixel ;
  else
  echo "ibl-neuropixel is up-to-date" ;
  fi
fi

conda deactivate
