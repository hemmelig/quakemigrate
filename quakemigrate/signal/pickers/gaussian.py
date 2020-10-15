# -*- coding: utf-8 -*-
"""
The default seismic phase picking class - fits a 1-D Gaussian to the calculated
onset functions.

"""

import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from quakemigrate.plot.phase_picks import pick_summary
import quakemigrate.util as util
from .base import PhasePicker


def calculate_mad(x, scale=1.4826):
    """
    Calculates the Median Absolute Deviation (MAD) of the input array x.

    Parameters
    ----------
    x : array-like
        Coalescence array in.
    scale : float, optional
        A scaling factor for the MAD output to make the calculated MAD factor
        a consistent estimation of the standard deviation of the distribution.

    Returns
    -------
    scaled_mad : array-like
        Array of scaled mean absolute deviation values for the input array, x,
        scaled to provide an estimation of the standard deviation of the
        distribution.

    """

    # Calculate median and mad values:
    med = np.apply_over_axes(np.median, x, 0)
    mad = np.median(np.abs(x - med), axis=0)

    return scale * mad


class GaussianPicker(PhasePicker):
    """
    This class details the default method of making phase picks shipped with
    QuakeMigrate, namely fitting a 1-D Gaussian function to the STA/LTA onset
    function trace for each station.

    Attributes
    ----------
    phase_picks : dict
            "GAU_P" : array-like
                Numpy array stack of Gaussian pick info (each as a dict)
                for P phase
            "GAU_S" : array-like
                Numpy array stack of Gaussian pick info (each as a dict)
                for S phase
    noise_mad_scalar : float
        Scalar value to multiply the Median Absolute Deviation (MAD) of the
        'noise' window by to determine the noise threshold.
    plot_picks : bool
        Toggle plotting of phase picks.

    Methods
    -------
    pick_phases(data, lut, event, event_uid, output)
        Picks phase arrival times for located earthquakes by fitting a 1-D
        Gaussian function to the P and S onset functions

    """

    DEFAULT_GAUSSIAN_FIT = {"popt": 0,
                            "xdata": 0,
                            "xdata_dt": 0,
                            "PickValue": -1}

    def __init__(self, onset=None, **kwargs):
        """Instantiate the GaussianPicker object."""
        super().__init__(**kwargs)

        self.onset = onset
        self.noise_mad_scalar = kwargs.get("noise_mad_scalar", 15.0)
        self.marginal_window = kwargs.get("marginal_window", 1.0)
        self.sampling_rate = None
        self.plot_picks = kwargs.get("plot_picks", False)

        if "fraction_tt" in kwargs.keys():
            print("FutureWarning: Fraction of traveltime argument moved to "
                  "lookup tables.\nIt remains possible to override the "
                  "fraction of traveltime here, if required, to further\ntune"
                  "the phase picker.")
        self._fraction_tt = kwargs.get("fraction_tt")

    def __str__(self):
        """Returns a short summary string of the GaussianPicker."""

        str_ = ("\tPhase picking by fitting a 1-D Gaussian to onsets\n"
                f"\t\tMAD noise scalar  = {self.noise_mad_scalar}\n"
                f"\t\tMarginal window = {self.marginal_window} s\n")
        if self._fraction_tt is not None:
            str_ += (f"\t\tSearch window   = {self._fraction_tt*100}% of "
                     "traveltime\n")

        return str_

    @util.timeit("info")
    def pick_phases(self, event, lut, run):
        """
        Picks phase arrival times for located earthquakes.

        Parameters
        ----------
        event : :class:`~quakemigrate.io.event.Event` object
            Contains pre-processed waveform data on which to perform picking,
            the event location, and a unique identifier.
        lut : :class:`~quakemigrate.lut.LUT` object
            Contains the traveltime lookup tables for seismic phases, computed
            for some pre-defined velocity model.
        run : :class:`~quakemigrate.io.Run` object
            Light class encapsulating i/o path information for a given run.

        Returns
        -------
        event : :class:`~quakemigrate.io.event.Event` object
            Event object provided to pick_phases(), but now with phase picks!
        picks : `pandas.DataFrame`
            DataFrame that contains the measured picks with columns:
            ["Name", "Phase", "ModelledTime", "PickTime", "PickError", "SNR"]
            Each row contains the phase pick from one station/phase.

        """

        # Onsets are recalculated without logging
        _ = self.onset.calculate_onsets(event.data, lut.phases, log=False)
        self.sampling_rate = self.onset.sampling_rate

        if self._fraction_tt is None:
            fraction_tt = lut.fraction_tt
        else:
            fraction_tt = self._fraction_tt

        e_ijk = lut.index2coord(event.hypocentre, inverse=True)[0]

        # Pre-define pick DataFrame and fit params and pick windows dicts
        p_idx = np.arange(sum([len(v) for _, v in event.data.onsets.items()]))
        picks = pd.DataFrame(index=p_idx,
                             columns=["Station", "Phase", "ModelledTime",
                                      "PickTime", "PickError", "SNR"])
        gaussfits = {}
        pick_windows = {}
        idx = 0

        for station, onsets in event.data.onsets.items():
            for phase, onset in onsets.items():
                traveltime = lut.traveltime_to(phase, e_ijk, station)[0]
                pick_windows.setdefault(station, {}).update(
                    {phase: self._determine_window(
                        event, traveltime, fraction_tt)})
                n_samples = len(onset)

            self._distinguish_windows(
                pick_windows[station], list(onsets.keys()), n_samples)

            for phase, onset in onsets.items():
                # Find threshold from 'noise' part of onset
                noise_threshold = self._find_noise_threshold(
                    onset, pick_windows[station])

                logging.debug(f"\t\tPicking {phase} at {station}...")
                fit, *pick = self._fit_gaussian(
                    onset, self.onset.gaussian_halfwidth(phase),
                    event.data.starttime, noise_threshold,
                    pick_windows[station][phase])

                gaussfits.setdefault(station, {}).update({phase: fit})

                traveltime = lut.traveltime_to(phase, e_ijk, station)[0]
                model_time = event.otime + traveltime
                picks.iloc[idx] = [station, phase, model_time, *pick]
                idx += 1

        event.add_picks(picks, gaussfits=gaussfits, pick_windows=pick_windows,
                        noise_mad_scalar=self.noise_mad_scalar)

        self.write(run, event.uid, picks)

        if self.plot_picks:
            logging.info("\t\tPlotting picks...")
            for station, onsets in event.data.onsets.items():
                traveltimes = [lut.traveltime_to(phase, e_ijk, station)[0]
                               for phase in onsets.keys()]
                self.plot(event, station, onsets, picks, traveltimes, run)

        return event, picks

    def _determine_window(self, event, tt, fraction_tt):
        """
        Determine phase pick window upper and lower bounds based on a set
        percentage of the phase travel time.

        Parameters
        ----------
        event : :class:`~quakemigrate.io.event.Event` object
            Contains pre-processed waveform data on which to perform picking,
            the event location, and a unique identifier.
        tt : float
            Traveltime for the requested phase.
        fraction_tt : float
            Defines width of time window around expected phase arrival time in
            which to search for a phase pick as a function of the traveltime
            from the event location to that station -- should be an estimate of
            the uncertainty in the velocity model.

        Returns
        -------
        lower_idx : int
            Index of lower bound for the phase pick window.
        arrival_idx : int
            Index of the phase arrival.
        upper_idx : int
            Index of upper bound for the phase pick window.

        """

        arrival_idx = util.time2sample(event.otime + tt - event.data.starttime,
                                       self.sampling_rate)

        # Add length of marginal window to this and convert to index
        samples = util.time2sample(tt * fraction_tt, self.sampling_rate)

        return [arrival_idx - samples, arrival_idx, arrival_idx + samples]

    def _distinguish_windows(self, windows, phases, samples):
        """
        Ensure pick windows do not overlap - if they do, set the upper bound of
        window one and the lower bound of window two to be the midpoint index
        of the two arrivals.

        Parameters
        ----------
        windows : dict
            Dictionary of windows with phases as keys.
        phases : list of str
            Phases being migrated.
        samples : int
            Total number of samples in the onset function.

        """

        # Handle first key
        first_idx = windows[phases[0]][0]
        windows[phases[0]][0] = 0 if first_idx < 0 else first_idx

        # Handle keys pairwise
        for p1, p2 in util.pairwise(phases):
            p1_window, p2_window = windows[p1], windows[p2]
            mid_idx = int((p1_window[2] + p2_window[0]) / 2)
            windows[p1][2] = min(mid_idx, p1_window[2])
            windows[p2][0] = max(mid_idx, p2_window[0])

        # Handle last key
        last_idx = windows[phases[-1]][2]
        windows[phases[-1]][2] = samples if last_idx > samples else last_idx

    def _find_noise_threshold(self, onset, windows):
        """
        Determine a pick threshold as some scalar times the Median Absolute
        Deviation of the onset data outside the pick windows.

        Parameters
        ----------
        onset : `numpy.ndarray` of `numpy.double`
            Onset (characteristic) function.
        windows : list of int
            Indexes of the lower window bound, the phase arrival, and the upper
            window bound.

        Return
        ------
        noise_threshold : float
            The threshold based on 'noise'.

        """

        onset_noise = onset.copy()
        for _, window in windows.items():
            onset_noise[window[0]:window[2]] = -1
        onset_noise = onset_noise[onset_noise > -1]

        # noise_threshold = np.percentile(onset_noise, self.pick_threshold * 100)
        med = np.median(onset_noise)
        mad = np.median(np.abs(onset_noise - med))

        return self.noise_mad_scalar * mad

    def _fit_gaussian(self, onset, halfwidth, starttime, noise_threshold, window):
        """
        Fit a Gaussian to the onset function in order to make a time pick with
        an associated uncertainty. Uses the same STA/LTA onset (characteristic)
        function as is migrated through the grid to calculate the earthquake
        location.

        Uses knowledge of approximate pick index, the short-term average
        onset window and the signal sampling rate to make an initial estimate
        of a gaussian fit to the onset function.

        Parameters
        ----------
        onset : `numpy.ndarray` of `numpy.double`
            Onset (characteristic) function.
        starttime : UTCDateTime object
            Start time of data (w_beg).
        p_arr : UTCDateTime object
            Time when P phase is expected to arrive based on best location.
        s_arr : UTCDateTime object
            Time when S phase is expected to arrive based on best location.

        Returns
        -------
        gaussian_fit : dictionary
            gaussian fit parameters: {"popt": popt,
                                      "xdata": x_data,
                                      "xdata_dt": x_data_dt,
                                      "PickValue": max_onset,
                                      "PickThreshold": threshold}
        max_onset : float
            amplitude of gaussian fit to onset function
        sigma : float
            sigma of gaussian fit to onset function
        mean : UTCDateTime
            mean of gaussian fit to onset function == pick time

        """

        # Trim the onset function in the pick window
        onset_signal = onset[window[0]:window[2]]

        # Calculate the pick threshold from the signal: either the half-maximum
        # or the 88th percentile (whichever is bigger)
        signal_threshold = min([np.max(onset_signal) / 2,
                                np.percentile(onset_signal, 88)])
        # Calculate the pick threshold: either user-specified scaled MAD of
        # data outside pick windows ('noise'), or the signal threshold
        # determined above (whichever is bigger).
        threshold = np.max([noise_threshold, signal_threshold])

        # If there is any data that meets this requirement...
        if (onset_signal > threshold).any():
            exceedence = np.where(onset_signal > threshold)[0]
            exceedence_dist = np.zeros(len(exceedence))

            # Really faffy process to identify the period of data which is
            # above the threshold around the highest value of the onset
            # function.
            d = 1
            e = 0
            while e < len(exceedence_dist) - 1:
                if e == len(exceedence_dist):
                    exceedence_dist[e] = d
                else:
                    if exceedence[e + 1] == exceedence[e] + 1:
                        exceedence_dist[e] = d
                    else:
                        exceedence_dist[e] = d
                        d += 1
                e += 1

            # Find the indices for this period of data
            tmp = exceedence_dist[np.argmax(onset_signal[exceedence])]
            tmp = np.where(exceedence_dist == tmp)

            # Add one data point below the threshold at each end of this period
            gau_idxmin = exceedence[tmp][0] + window[0] - 1
            gau_idxmax = exceedence[tmp][-1] + window[0] + 2

            # Select data to fit the gaussian to
            x_data = np.arange(gau_idxmin, gau_idxmax, dtype=float)
            x_data = x_data / self.sampling_rate
            y_data = onset[gau_idxmin:gau_idxmax]

            # Convert indices to times
            x_data_dt = np.array([])
            for _, x in enumerate(x_data):
                x_data_dt = np.hstack([x_data_dt, starttime + x])

            # Try to fit a 1-D Gaussian.
            try:
                # Initial parameters are:
                #  height = max value of onset function
                #  mean   = time of max value
                #  sigma  = data half-range (calculated above)
                p0 = [np.max(y_data),
                      float(gau_idxmin + np.argmax(y_data))
                      / self.sampling_rate,
                      halfwidth / self.sampling_rate]

                # Do the fit
                popt, _ = curve_fit(util.gaussian_1d, x_data, y_data, p0)

                # Results:
                #  popt = [height, mean (seconds), sigma (seconds)]
                max_onset = popt[0]
                # Convert mean (pick time) to time
                mean = starttime + float(popt[1])
                sigma = np.absolute(popt[2])

                # Check pick mean is within the pick window.
                if not gau_idxmin < popt[1] * self.sampling_rate < gau_idxmax:
                    logging.debug("\t\t    Pick mean out of bounds - "
                                 "continuing.")
                    gaussian_fit = self.DEFAULT_GAUSSIAN_FIT.copy()
                    gaussian_fit["PickThreshold"] = threshold
                    sigma = -1
                    mean = -1
                    max_onset = -1
                else:
                    gaussian_fit = {"popt": popt,
                                    "xdata": x_data,
                                    "xdata_dt": x_data_dt,
                                    "PickValue": max_onset,
                                    "PickThreshold": threshold}

            # If curve_fit fails. Will also spit error message to stdout,
            # though this can be suppressed  - see warnings.filterwarnings()
            except (ValueError, RuntimeError):
                logging.debug("\t\t    Failed curve_fit - continuing.")
                gaussian_fit = self.DEFAULT_GAUSSIAN_FIT.copy()
                gaussian_fit["PickThreshold"] = threshold
                sigma = -1
                mean = -1
                max_onset = -1

        # If onset function does not exceed threshold in pick window
        else:
            logging.debug("\t\t    No onset signal exceeding threshold "
                          f"({threshold:5.3f}) - continuing.")
            gaussian_fit = self.DEFAULT_GAUSSIAN_FIT.copy()
            gaussian_fit["PickThreshold"] = threshold
            sigma = -1
            mean = -1
            max_onset = -1

        return gaussian_fit, mean, sigma, max_onset

    @util.timeit()
    def plot(self, event, station, onsets, picks, traveltimes, run):
        """
        Plot figure showing the filtered traces for each data component and the
        characteristic functions calculated from them (P and S) for each
        station. The search window to make a phase pick is displayed, along
        with the dynamic pick threshold (defined as a percentile of the
        background noise level), the phase pick time and its uncertainty (if
        made) and the Gaussian fit to the characteristic function.

        Parameters
        ----------
        event_uid : str, optional
            Earthquake UID string; for subdirectory naming within directory
            {run_path}/traces/

        """

        fpath = run.path / f"locate/{run.subname}/pick_plots/{event.uid}"
        fpath.mkdir(exist_ok=True, parents=True)

        signal = event.data.filtered_waveforms.select(station=station)
        # Check if any data available to plot
        if not bool(signal):
            return
        stpicks = picks[picks["Station"] == station].reset_index(drop=True)
        window = event.picks["pick_windows"][station]

        # Call subroutine to plot basic phase pick figure
        fig = pick_summary(event, station, signal, stpicks, onsets,
                           traveltimes, window)

        # --- Gaussian fits ---
        axes = fig.axes
        phases = [phase for phase, _ in onsets.items()]
        onsets = [onset for _, onset in onsets.items()]
        for j, (ax, ph) in enumerate(zip(axes[3:5], phases)):
            gau = event.picks["gaussfits"][station][ph]
            win = window[ph]

            # Plot threshold
            thresh = gau["PickThreshold"]
            norm = max(onsets[j][win[0]:win[2]+1])
            ax.axhline(thresh / norm, label="Pick threshold")
            axes[5].text(0.05+j*0.5, 0.25, f"Threshold: {thresh:5.3f}",
                         ha="left", va="center", fontsize=18)

            # Check pick has been made
            if not gau["PickValue"] == -1:
                yy = util.gaussian_1d(gau["xdata"], gau["popt"][0],
                                      gau["popt"][1], gau["popt"][2])
                dt = [x.datetime for x in gau["xdata_dt"]]
                ax.plot(dt, yy / norm)

        # --- Picking windows ---
        # Generate plottable timestamps for data
        times = event.data.times(type="matplotlib")
        for j, ax in enumerate(axes[:5]):
            win = window[phases[0]] if j % 3 == 0 else window[phases[-1]]
            clr = "#F03B20" if j % 3 == 0 else "#3182BD"
            ax.fill_betweenx([-1.1, 1.1], times[win[0]], times[win[2]],
                             alpha=0.2, color=clr, label="Picking window")

        for ax in axes[3:5]:
            ax.legend(fontsize=14)

        fstem = f"{event.uid}_{station}"
        file = (fpath / fstem).with_suffix(".pdf")
        plt.savefig(file)
        plt.close(fig)

    @property
    def fraction_tt(self):
        """Handler for deprecated attribute 'fraction_tt'"""
        return self._fraction_tt

    @fraction_tt.setter
    def fraction_tt(self, value):
        print("FutureWarning: Fraction of traveltime attribute has moved to "
              "lookup table.\n Overriding...")
        self._fraction_tt = value   

    @property
    def pick_threshold(self):
        """Handler for deprecated attribute 'pick_threshold'"""
        return self._pick_threshold

    @pick_threshold.setter
    def pick_threshold(self, value):
        print("FutureWarning: 'pick_threshold' parameter has been deprecated.",
              "\nPlease use the new 'noise_mad_scalar', which is the "
              "scale factor to multiply the MAD of the noise by.")
