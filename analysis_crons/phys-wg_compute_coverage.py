"""
This script computes the coverage of the brain regions and upload to AWS for use in pinpoint
requirements:
-   ibllib
-   iblapps
"""
import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

from one.api import ONE
from one.remote import aws
from ibllib.atlas import atlas
from ibllib.atlas.regions import BrainRegions
from needles2.probe_model import ProbeModel

##
'''
===========================
   PARAMETERS
===========================
'''
PATH_COVERAGE = Path('/datadisk/Coverage')

'''
===========================
   BRAIN REGION COVERAGE
===========================
'''
# Overwrite according to Nick's selection
# https://docs.google.com/spreadsheets/d/1d6ghPpc2FT4D5t2n6eKYk8IcoOG4RgChaVLhazek04c/edit#gid=1168745718
acronyms_region_cov = ['AD', 'AHN', 'AUDpo', 'CL', 'COAa', 'FN', 'GPi', 'IO',
                       'PG', 'RE', 'STN', 'VTA']


# Instantiate brain atlas and one
one = ONE(base_url="https://alyx.internationalbrainlab.org")  # makes sure we're on the private database
ba = atlas.AllenAtlas(25)
ba.compute_surface()
br = BrainRegions()
# Remap volume from Allen to Beryl
label_beryl = ba.regions.mappings['Beryl'][ba.label]
# Get volume of acronyms
mapped_atlas_ac = br.acronym[label_beryl]  # TODO could be done faster by remapping list of brain reg to ID instead

# Saving paths
filepath_sp_vol = PATH_COVERAGE.joinpath('volume_test', 'second_pass_volume.npy')
filepath_coverage = PATH_COVERAGE.joinpath('test', 'coverage.npy')
filepath_df_cov_val = filepath_coverage.parent.joinpath('df_cov_val.csv')
filepath_sp_per012 = filepath_coverage.parent.joinpath('sp_per012.npy')
filepath_coverage_pinpoint = filepath_coverage.parent.joinpath('coverage_pinpoint.bytes')

if not filepath_sp_vol.exists():
    s3, bucket_name = aws.get_s3_from_alyx(alyx=one.alyx)
    aws.s3_download_file('resources/physcoverage/second_pass_volume.npy',
                         filepath_sp_vol, s3=s3, bucket_name=bucket_name)

# Compute date to input in df
datenow = datetime.datetime.now()
datefile = datenow.strftime('%Y-%m-%d')


##
'''
============================
    VOLUMETRIC COVERAGE
============================
'''
# Prepare SP volume
sp_volume = np.load(filepath_sp_vol)
sp_volume[sp_volume == 0] = np.nan
sp_volume = 2 * sp_volume
# Remove areas from this volume # 20th April 2023 decision - Phys WG
acronym_remove_sp = ['MOB', 'AOB', 'AOBgr', 'onl', 'AOBmi']
# === BRAIN REGION ===
for i_acronym in acronym_remove_sp:
    sp_volume[np.where(br.acronym[ba.label] == i_acronym)] = np.nan
    # Note : Use Allen parcellation instead of Beryl (mapped_atlas_ac) as not all voxels contained in aggregates
sp_voxels = np.where(~np.isnan(sp_volume.flatten()))[0]

# Init volume of points
breg_points = ba.label.copy()
breg_points[:] = 0
# For each brain region of interest, find voxel and priority, and assign point number
for i_acronym in acronyms_region_cov:
    breg_points[np.where(mapped_atlas_ac == i_acronym)] = 10

# Compute coverage (overwrite)
dist = 354
django_str = []
pr = ProbeModel(ba=ba, lazy=True)
pr.get_traj_for_provenance('Planned', django=django_str)
pr.get_traj_for_provenance('Micro-manipulator', django=django_str)
pr.get_traj_for_provenance('Histology track', django=django_str)
pr.get_traj_for_provenance('Ephys aligned histology track', django=django_str)
pr.get_traj_for_provenance(provenance='Ephys aligned histology track',
                           django=django_str + ['probe_insertion__json__extended_qc__'
                                                'alignment_resolved,True'], prov_dict='Resolved')
pr.find_traj_is_best(provenance='Planned')
pr.find_traj_is_best(provenance='Micro-manipulator')
pr.find_traj_is_best(provenance='Histology track')
pr.find_traj_is_best(provenance='Ephys aligned histology track')
pr.traj['Resolved']['is_best'] = np.arange(len(pr.traj['Resolved']['traj']))
pr.get_insertions_with_xyz()
pr.compute_best_for_provenance('Planned')

trajs = pr.traj['Best']['traj']
coverage, sp_per0, sp_per1, sp_per2 = pr.compute_coverage(trajs, dist_fcn=[dist, dist + 1], pl_voxels=sp_voxels)
# Save aggregate for fastness of report later
df_coverage_vals = pd.DataFrame.from_dict({"0": [sp_per0[-1]], "1": [sp_per1[-1]], "2": [sp_per2[-1]],
                                           "date": [datefile]})
##
'''
============================
    COMBINE COVERAGES
============================

'''
# === VOLUMETRIC COVERAGE ===
cov_points = coverage.copy()
# Remove values outside SP mask and make sure all values for 2+ probes are 2
cov_points[np.isnan(sp_volume)] = np.nan
cov_points[np.where(cov_points > 2)] = 2
# Assign points
cov_points[np.where(cov_points == 0)] = 30
cov_points[np.where(cov_points == 1)] = 50
cov_points[np.where(cov_points == 2)] = 0
cov_points[np.isnan(cov_points)] = 0  # For summing

# === BRAIN REGION ===
# Init volume of points
breg_points = ba.label.copy()
breg_points[:] = 0
# For each brain region of interest, find voxel and priority, and assign point number
for i_acronym in acronyms_region_cov:
    breg_points[np.where(mapped_atlas_ac == i_acronym)] = 10

# === SUM the 2 matrices ===
sum_points = breg_points + cov_points
sum_points[np.where(sum_points == 0)] = np.nan

# Restrict to SP mask
sum_points[np.isnan(sp_volume)] = np.nan

# Save locally
filepath_coverage.parent.mkdir(exist_ok=True, parents=True)
np.save(filepath_coverage, sum_points)
np.save(filepath_sp_per012, [sp_per0, sp_per1, sp_per2])
df_coverage_vals.to_csv(filepath_df_cov_val)
# Save into format for Pinpoint
coverage = sum_points.copy()
coverage[np.isnan(coverage)] = 0
with open(filepath_coverage_pinpoint, 'wb') as f:
    f.write(coverage.astype(np.uint8).flatten().tobytes())

# upload to AWS  Sync to AWS

os.system(f"aws --profile ibl s3 cp {filepath_coverage} "
          f"s3://ibl-brain-wide-map-private/resources/physcoverage/{filepath_coverage.name}")
os.system(f"aws --profile ibl s3 cp {filepath_df_cov_val} "
          f"s3://ibl-brain-wide-map-private/resources/physcoverage/{filepath_df_cov_val.name}")
os.system(f"aws --profile ibl s3 cp {filepath_sp_per012} "
          f"s3://ibl-brain-wide-map-private/resources/physcoverage/{filepath_sp_per012.name}")
os.system(f"aws --profile ibl s3 cp {filepath_coverage_pinpoint} "
          f"s3://ibl-brain-wide-map-private/resources/physcoverage/{filepath_coverage_pinpoint.name}")
# Add to public bucket too for Pinpoint access
os.system(f"aws --profile ibl s3 cp {filepath_coverage_pinpoint} "
          f"s3://ibl-brain-wide-map-public/phys-coverage-2023/{filepath_coverage_pinpoint.name}")
