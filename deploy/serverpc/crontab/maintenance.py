from pathlib import Path
import logging
import os
from datetime import datetime
import shutil
from oneibl.one import ONE
import alf.io
import ibllib.io.raw_data_loaders as raw
from ibllib.ephys import spikes
from ibllib.pipes.local_server import _get_lab
from ibllib.io import spikeglx
from ibllib.pipes.ephys_preprocessing import SpikeSorting_KS2_Matlab
from oneibl.registration import register_dataset

ROOT_PATH = Path('/mnt/s0/Data/Subjects')

_logger = logging.getLogger('ibllib')


def correct_ephys_manual_video_copies():
    """
    """
    for flag in ROOT_PATH.rglob('ephys_data_transferred.flag'):
        video = True
        passive = True
        behaviour = True
        session_path = alf.io.get_session_path(flag)
        avi_files = list(session_path.joinpath('raw_video_data').glob('*.avi'))

        if len(avi_files) < 3:
            video = False
        if not session_path.joinpath('raw_behavior_data').exists():
            behaviour = False
        if not session_path.joinpath('raw_passive_data').exists():
            passive = False
        _logger.info(f"{session_path} V{video}, B{behaviour}, P{passive}")


def correct_flags_biased_in_ephys_rig():
    """
    Biased sessions acquired on ephys rigs do not convert video transferred flag
    To not interfere with ongoing transfers, only handle sessions that are older than 7 days
    """
    N_DAYS = 7
    for flag in ROOT_PATH.rglob('video_data_transferred.flag'):
        session_path = alf.io.get_session_path(flag)
        ses_date = datetime.strptime(session_path.parts[-2], "%Y-%M-%d")
        if (datetime.now() - ses_date).days > N_DAYS:
            settings = raw.load_settings(session_path)
            if 'ephys' in settings['PYBPOD_BOARD'] and settings['PYBPOD_PROTOCOL']\
                    == '_iblrig_tasks_biasedChoiceWorld':
                _logger.info(session_path)
                flag.unlink()
                session_path.joinpath('raw_session.flag').touch()


def correct_passive_in_wrong_folder():
    """
    Finds the occasions where the data has been transferred manually and the passive folder has
    has not been moved and got the correct file structure
    """
    one = ONE()
    lab = _get_lab(one)
    if lab[0] == 'wittenlab':

        for flag in ROOT_PATH.rglob('passive_data_for_ephys.flag'):
            passive_data_path = alf.io.get_session_path(flag)
            passive_session = passive_data_path.stem
            passive_folder = passive_data_path.joinpath('raw_behavior_data')
            sessions = os.listdir(passive_data_path.parent)

            # find the session number that isn't
            data_sess = [sess for sess in sessions if sess != passive_session]
            if len(data_sess) == 1:
                session_path = passive_data_path.parent.joinpath(data_sess[0])
            else:
                # If more than one we register passive to the latest one
                data_sess.sort()
                session_path = passive_data_path.parent.joinpath(data_sess[-1])

            # copy the file
            data_path = session_path.joinpath('raw_passive_data')
            shutil.copytree(passive_folder, data_path)
            _logger.info(f'moved {passive_folder} to {data_path}')

            # remove the passive flag
            flag.unlink()

            # find the tasks for this session and set it to waiting
            eid = one.eid_from_path(session_path)
            if eid:
                tasks = one.alyx.rest('tasks', 'list', session=eid, name='TrainingRegisterRaw')
                if len(tasks) > 0:
                    stat = {'status': 'Waiting'}
                    one.alyx.rest('tasks', 'partial_update', id=tasks[0]['id'], data=stat)

    else:
        return


def spike_amplitude_patching():
    """
    Patch the datasets that have incorrect spikes.amplitude datasets. While doing it also look for
    sessions that have spikesorting/ alf folders but for some reason haven't been registered and
    uploaded to flatiron for some reason (normally because .cbin file is missing)

    Five different scenarios to consider
    1. Data extracted properly, is on flatiron and has templates.amps - do nothing
    2. Data extracted properly, is on flatiron but doesn't have templates.amps - phy convert
       and register
    3. Data extracted properly with templates.amps , but not on flatiron - phy convert and
       register (don't necessarily need to phy convert but double check in case it was the
       syncing that errored)
    4. Data extracted properly without templates.amps, but non on flatiron - phy convert and
       register
    5. Data spike sorted but not extracted - phy convert and register

    """

    def phy2alf_conversion(session_path, ks2_path, alf_path, probe_label):
        try:
            # Find spikeglx meta data files associated with the session and probe
            files = spikeglx.glob_ephys_files(session_path, ext='meta')
            ap_files = [(ef.get("ap"), ef.get("label")) for ef in files if "ap" in ef.keys()]
            meta_file = next(ap[0] for ap in ap_files if ap[1] == probe_label)

            # The .cbin file doesn't always still exist on server so point to it from meta
            ap_file = meta_file.with_suffix('.cbin')

            # Convert to alf format
            spikes.ks2_to_alf(
                ks2_path,
                bin_path=meta_file.parent,
                out_path=alf_path,
                bin_file=None,
                ampfactor=SpikeSorting_KS2_Matlab._sample2v(ap_file))

            # Sync the probes
            out_files, _ = spikes.sync_spike_sorting(ap_file=ap_file, out_path=alf_path)

            return 0, out_files, None

        except BaseException as err:
            _logger.error(f'{session_path} and {probe_label} errored with message: {err}')

            return -1, None, err

    def add_note_to_insertion(eid, probe, one, msg=None):
        insertion = one.alyx.rest('insertions', 'list', session=eid, name=probe)

        if len(insertion) > 0:
            probe_id = insertion[0]['id']
            status_note = {'user': 'mayo',
                           'content_type': 'probeinsertion',
                           'object_id': probe_id,
                           'text': f'amps_patching_local_server: {msg}'}
            _ = one.alyx.rest('notes', 'create', data=status_note)
        else:
            # If the probe insertion doesn't exist, make a session note
            status_note = {'user': 'mayo',
                           'content_type': 'session',
                           'object_id': eid,
                           'text': f'amps_patching_local_server: {msg}'}
            _ = one.alyx.rest('notes', 'create', data=status_note)

    one = ONE()

    for ks2_out in ROOT_PATH.rglob('spike_sorting_ks2.log'):
        ks2_path = Path(ks2_out).parent

        # If we already looked at this session previously, no need to try again
        if ks2_path.joinpath('amps_patching_local_server.flag').exists():
            continue

        # Make the flag if it is the first time looking into session
        ks2_path.joinpath('amps_patching_local_server.flag').touch()

        # Now proceed with everything else
        session_path = alf.io.get_session_path(ks2_out)
        eid = one.eid_from_path(session_path)
        if eid is None:
            # Skip sessions that don't exist on alyx!
            continue
        probe = ks2_path.stem
        alf_path = session_path.joinpath('alf', probe)
        alf_path.mkdir(parents=True, exist_ok=True)

        # If a clusters.metrics file exists in the alf_path, delete it. Causes registration error!
        cluster_metrics = alf_path.joinpath('clusters.metrics.csv')
        if cluster_metrics.exists():
            os.remove(cluster_metrics)

        # templates.amps file only exists if it is new phy extractor
        templates_file = alf_path.joinpath('templates.amps.npy')
        if templates_file.exists():
            dset = one.alyx.rest('datasets', 'list', session=eid, name='templates.amps.npy')
            if len(dset) > 0:
                # In this case data is on flatiron, no need to do anything
                continue
            else:
                # In this case data is in alf format but hasn't been registered, reconvert just
                # to make sure and register
                status, out, err = phy2alf_conversion(session_path, ks2_path, alf_path, probe)
                if status == 0:
                    _logger.info(f'Case non registered: all good for {session_path} and {probe}')
                    register_dataset(out, one=one)
                    add_note_to_insertion(eid, probe, one, msg='completed')
                else:
                    # Log the error
                    add_note_to_insertion(eid, probe, one, msg=err)
                    continue
        else:
            # In this case either old amplitude extraction or alf extraction hasn't happened at all
            status, out, err = phy2alf_conversion(session_path, ks2_path, alf_path, probe)
            if status == 0:
                _logger.info(f'Case non extracted: all good for {session_path} and {probe}')
                add_note_to_insertion(eid, probe, one, msg='completed')
                register_dataset(out, one=one)
            else:
                # Log the error
                add_note_to_insertion(eid, probe, one, msg=err)
                continue


if __name__ == "__main__":
    correct_flags_biased_in_ephys_rig()
    correct_ephys_manual_video_copies()
    spike_amplitude_patching()
    correct_passive_in_wrong_folder()
