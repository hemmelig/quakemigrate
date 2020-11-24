# -*- coding: utf-8 -*-
"""
This script demonstrates how to run the locate stage of QuakeMigrate.

For more details, please see the manual and read the docs.

"""

# Stop numpy using all available threads (these environment variables must be
# set before numpy is imported for the first time).
import os
os.environ.update(OMP_NUM_THREADS="1",
                  OPENBLAS_NUM_THREADS="1",
                  NUMEXPR_NUM_THREADS="1",
                  MKL_NUM_THREADS="1")

from obspy.core import AttribDict

from quakemigrate import QuakeScan
from quakemigrate.io import Archive, read_lut, read_response_inv, read_stations
from quakemigrate.signal.onsets import STALTAOnset
from quakemigrate.signal.pickers import GaussianPicker
from quakemigrate.signal.local_mag import LocalMag

# --- i/o paths ---
archive_path = "/path/to/archived/data"
lut_file = "/path/to/lut"
station_file = "/path/to/station_file"
response_file = "/path/to/response_file"

run_path = "/path/to/output"
run_name = "name_of_run"

# --- Set time period over which to run locate ---
starttime = "2018-001T00:00:00.0"
endtime = "2018-002T00:00:00.0"

# --- Read in station file ---
stations = read_stations(station_file)

# --- Read in response inventory
response_inv = read_response_inv(response_file)

# --- Create new Archive and set path structure ---
archive = Archive(archive_path=archive_path, stations=stations,
                  archive_format="YEAR/JD/STATION", response_inv=response_inv)
# For custom structures...
# archive.format = "custom/archive_{year}_{jday}/{month:02d}-{day:02d}.{station}_structure"

# --- Resample data with mismatched sampling rates ---
# archive.resample = True
# archive.upfactor = 2

# --- Load the LUT ---
lut = read_lut(lut_file=lut_file)

# --- Decimate the lookup table ---
# lut = lut.decimate([1, 1, 1])

# --- Create new Onset function ---
onset = STALTAOnset(position="centred", sampling_rate=20)
onset.phases = ["P", "S"]
onset.bandpass_filters = {
    "P": [2, 9.9, 2],
    "S": [2, 9.9, 2]}
onset.sta_lta_windows = {
    "P": [0.2, 1.5],
    "S": [0.2, 1.5]}

# --- Create new PhasePicker ---
# For a complete list of parameters and guidance on how to choose them, please
# see the manual and read the docs.
gausspicker_onset = STALTAOnset(position="centred", sampling_rate=20)
gausspicker_onset.phases = ["P", "S"]
gausspicker_onset.bandpass_filters = {
    "P": [2, 9.9, 2],
    "S": [2, 9.9, 2]}
gausspicker_onset.sta_lta_windows = {
    "P": [0.2, 1.5],
    "S": [0.2, 1.5]}

picker = GaussianPicker(onset=gausspicker_onset)
picker.plot_picks = True

# --- Create new LocalMag object ---
# All parameters are optional: see the documentation for a complete guide.
amp_params = AttribDict()
amp_params.water_level = 60
amp_params.signal_window = 5.
amp_params.bandpass_filter = True
amp_params.bandpass_lowcut = 2.
amp_params.bandpass_highcut = 20.
amp_params.remove_full_response = False

# A0 attenuation function is required: see the documentation for several
# built-in options, or specify your own function. All other parameters are
# optional - see the documentation for a complete guide.
mag_params = AttribDict()
mag_params.A0 = "Hutton-Boore"  # NOTE: REQUIRED PARAMETER!
mag_params.use_hyp_dist = False
mag_params.amp_feature = "S_amp"
mag_params.station_corrections = {}
mag_params.trace_filter = ".[BH]H[NE]$"
mag_params.noise_filter = 1.
mag_params.station_filter = ["KVE", "LIND"]
mag_params.dist_filter = False

mags = LocalMag(amp_params=amp_params, mag_params=mag_params)
mags.plot_amplitudes = True

# --- Create new QuakeScan ---
# If you do not want to calculate local magnitudes, specify `mags=None`
scan = QuakeScan(archive, lut, onset=onset, picker=picker, mags=mags,
                 run_path=run_path, run_name=run_name, log=True,
                 loglevel="info")

# --- Set locate parameters ---
# For a complete list of parameters and guidance on how to choose them, please
# see the manual and read the docs.
scan.marginal_window = 1
scan.threads = 12

# --- Toggle plotting options ---
scan.plot_event_summary = True
# It is possible to supply xy files to enhance and give context to the
# event summary map plots. See the volcano-tectonic example from Iceland
# for details.
# scan.xy_files = "/path/to/xy_csv"

# --- Toggle writing of cut waveforms ---
scan.write_cut_waveforms = True
scan.pre_cut = 20.
scan.post_cut = 60.

# --- Run locate ---
# Between two timestamps
scan.locate(starttime=starttime, endtime=endtime)
# From a triggered events file.
# scan.locate(trigger_file="filename_of_triggered_events")
