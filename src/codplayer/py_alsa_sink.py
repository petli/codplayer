# codplayer - base class for the audio devices
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import array

import time
import sys
import threading
import alsaaudio

from . import sink
from . import model

class PyAlsaSink(sink.Sink):
    """Very simple ALSA sink in only Python.  The C version has a
    separate thread to ensure that the device play loop runs without
    interferance from the Python GC or Big Interpreter Lock, but we
    don't gain anything from that here.

    There may be some race conditions around pause/resume if things go
    haywire in the sink thread at the same time, but this code does
    not attempt to fix that.
    """

    # Run on approx 10 Hz.  pyalsaaudio will hardcode the hardware buffer to
    # four periods.
    PERIOD_SIZE = 4096

    def __init__(self, player, card, start_without_device, log_performance):
        self.log = player.log
        self.debug = player.debug
        self.alsa_card = card

        # State attributes protected by lock

        self.lock = threading.Lock()

        self.alsa_pcm = None
        self.paused = False

        # End of thread state attributes

        # State attributes only used within the sink thread
        self.channels = None
        self.bytes_per_sample = None
        self.rate = None
        self.big_endian = None
        self.alsa_swap_bytes = False
        self.period_bytes = None

        self.partial_period = None
        self.partial_packet = None
        self.device_error = None

        # End of sink thread state attributes

        self.log("using python implementation of ALSA sink - you might get glitchy sound");

        # See if we can open the device, just for logging purposes -
        # this will be properly handled in start().

        try:
            self.debug('alsa: opening device for card: {0}', self.alsa_card)
            pcm = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK,
                                mode = alsaaudio.PCM_NORMAL,
                                card = self.alsa_card)
            pcm.close()
        except alsaaudio.ALSAAudioError, e:
            if self.start_without_device:
                self.log('alsa: error opening card {0}: {1}',
                         self.alsa_card, e)
                self.log('alsa: proceeding since start_without_device = True')
                self.device_error = str(e)
            else:
                raise sink.SinkError(e)


    def pause(self):
        with self.lock:
            if self.alsa_pcm:
                try:
                    if not self.paused:
                        self.alsa_pcm.pause(1)
                        self.paused = True
                    return True
                except alsaaudio.ALSAAudioError, e:
                    self.log('error while pausing: {0}', e)

        return False


    def resume(self):
        with self.lock:
            if self.paused:
                self.paused = False
                if self.alsa_pcm:
                    try:
                        self.alsa_pcm.pause(0)
                    except alsaaudio.ALSAAudioError, e:
                        self.log('error while resuming: {0}', e)


    def stop(self):
        with self.lock:
            pcm = self.alsa_pcm
            paused = self.paused
            self.alsa_pcm = None
            self.device_error = None
            self.paused = False

        # pyalsaaudio will drain the buffer on close, no way around that
        if pcm:
            try:
                # And since it drains, it can't be paused
                if paused:
                    pcm.pause(0)
                pcm.close()
            except alsaaudio.ALSAAudioError, e:
                self.log('PyAlsaSink.stop: error when closing: {0}'.format(e))


    def start(self, channels, bytes_per_sample, rate, big_endian):
        self.channels = channels
        self.bytes_per_sample = bytes_per_sample
        self.rate = rate
        self.big_endian = big_endian
        self.paused = False
        self._try_open_pcm()


    def add_packet(self, data, packet):
        """Push data into the device.  To quickly(ish) react to
        transport state changes we're not looping here, but rather
        lets the sink thread do that.
        """

        stored = 0

        if self.partial_period:
            # Append to left-overs from last call
            stored = min(self.period_bytes - len(self.partial_period), len(data))

            if stored > 0:
                self.partial_period += str(buffer(data, 0, stored))
            else:
                assert stored == 0

            packet = self.partial_packet

            if len(self.partial_period) == self.period_bytes:
                if self._play_period(self.partial_period):
                    self.partial_period = None
                    self.partial_packet = None

        elif len(data) >= self.period_bytes:
            # At least one whole period to push into the device
            if self._play_period(buffer(data, 0, self.period_bytes)):
                stored = self.period_bytes

        else:
            # Not enough data for a whole period, save it for the next call
            assert len(data) < self.period_bytes
            self.partial_period = str(data)
            self.partial_packet = packet
            stored = len(data)

        return stored, packet, self.device_error


    def drain(self):
        if self.partial_period:
            # Pad final packet and push into buffer
            n = self.period_bytes - len(self.partial_period)
            if n > 0:
                self.partial_period = self.partial_period + ('\0' * n)

            packet = self.partial_packet

            if self._play_period(self.partial_period):
                self.partial_period = None
                self.partial_packet = None

            # Always return here to ensure feedback on last packet.
            # We'll get called again to drain properly after this.
            return packet, self.device_error

        # pyalsaaudio will (here usefully) drain before closing
        with self.lock:
            pcm = self.alsa_pcm
            paused = self.paused
            self.alsa_pcm = None
            self.device_error = None
            self.paused = False

        try:
            # Ensure we're not paused so this can drain
            if paused:
                pcm.pause(0)
            pcm.close()
        except alsaaudio.ALSAAudioError, e:
            self.log('PyAlsaSink.drain: error when closing: {0}'.format(e))

        return None


    def _play_period(self, data):
        with self.lock:
            pcm = self.alsa_pcm

        if pcm is None:
            pcm = self._try_open_pcm()
            if pcm is None:
                # Don't busyloop here
                time.sleep(3)
                return False

        if self.alsa_swap_bytes:
            # Heavy-handed assumptions about data formats etc
            a = array.array('h', str(data))
            assert a.itemsize == 2
            a.byteswap()
            data = a.tostring()

        try:
            n = pcm.write(data)
            return n > 0
        except alsaaudio.ALSAAudioError, e:
            self.log('alsa: error writing to device: {0}', e)
            self.device_error = str(e)

            with self.lock:
                self.alsa_pcm = None

            try:
                pcm.close()
            except alsaaudio.ALSAAudioError, e:
                self.log('alsa: ignoring error when closing after write failure: {0}', e)

            return False


    def _try_open_pcm(self):
        try:
            pcm = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK,
                                mode = alsaaudio.PCM_NORMAL,
                                card = self.alsa_card)

        except alsaaudio.ALSAAudioError, e:
            self.log('alsa: error opening card {0}: {1}',
                     self.alsa_card, e)
            return None

        if self._set_device_format(pcm):
            if self.paused:
                # Reopen into the right state
                try:
                    pcm.pause(1)
                except alsaaudio.ALSAAudioError, e:
                    self.log('error while trying to pause newly opened device: {0}', e)
                    pcm.close()
                    pcm = None

            with self.lock:
                self.alsa_pcm = pcm
            return pcm
        else:
            pcm.close()
            return None


    def _set_device_format(self, pcm):
        if self.big_endian:
            format = alsaaudio.PCM_FORMAT_S16_BE
        else:
            format = alsaaudio.PCM_FORMAT_S16_LE

        try:
            v = pcm.setformat(format)

            # Card accepts CD byte order
            if v == format:
                self.alsa_swap_bytes = False

            # Try byte swapped order instead
            else:
                self.debug('alsa: swapping bytes')
                self.alsa_swap_bytes = True

                if format == alsaaudio.PCM_FORMAT_S16_BE:
                    format = alsaaudio.PCM_FORMAT_S16_LE
                else:
                    format = alsaaudio.PCM_FORMAT_S16_BE

                v = pcm.setformat(format)
                if v != format:
                    self.log("alsa: can't set S16_BE/S16_LE format, card stuck on {0}", v)
                    self.device_error = "sample format not accepted"
                    return False


            v = pcm.setrate(self.rate)
            if v != self.rate:
                self.log("alsa: can't set rate to {0}, card stuck on {1}", self.rate, v)
                self.device_error = "sample format not accepted"
                return False

            v = pcm.setchannels(self.channels)
            if v != self.channels:
                self.log("alsa: can't set channels to {0}, card stuck on {1}", self.channels, v)
                self.device_error = "sample format not accepted"
                return False

            v = pcm.setperiodsize(self.PERIOD_SIZE)
            if v != self.PERIOD_SIZE:
                self.log('alsa: card refused our period size of {0}, using {1} instead',
                         self.PERIOD_SIZE, v)

            self.period_bytes = v * self.channels * self.bytes_per_sample
            return True

        except alsaaudio.ALSAAudioError, e:
            self.log('alsa: error setting format: {0}', e)
            self.device_error = str(e)
            return False


