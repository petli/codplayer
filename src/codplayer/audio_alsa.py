# codplayer - base class for the audio devices
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import array

import time
import sys
import threading

from . import audio
from . import model

class AlsaDevice(audio.ThreadDevice):
    """ALSA sound playback device.

    This will use a C module when available, otherwise fall back on
    the PythonAlsaThread class that uses pyalsadevice.
    """

    def __init__(self, player, config):
        super(AlsaDevice, self).__init__(player, config)

        self.alsa_thread = AlsaThread(
            self,
            self.config.alsa_card,
            self.config.start_without_device,
            
            # Hardcode to CD PCM format for now.
            model.PCM.channels,
            model.PCM.bytes_per_sample,
            model.PCM.rate,
            model.PCM.big_endian)
        

    def pause(self):
        self.alsa_thread.pause()

    def resume(self):
        self.alsa_thread.resume()

    def thread_play_stream(self, stream):
        first_packet = True

        try:
            for packet in stream:

                # When starting playing, set the packet directly as
                # the buffer is likely empty
                if first_packet:
                    self.set_current_packet(packet)
                    first_packet = False

                buf = buffer(packet.data)

                while len(buf) > 0:
                    stored, current_packet, device_error = self.alsa_thread.playing(buf, packet)

                    if current_packet:
                        self.set_current_packet(current_packet)

                    self.set_device_error(device_error)

                    if stored > 0:
                        # move forward in data buffer
                        buf = buffer(buf, stored)


        except audio.StreamAbort:
            self.alsa_thread.discard_buffer()
            raise

        # Wait for queued data to finish playing

        while not self.alsa_thread.buffer_empty():
            stored, current_packet, device_error = self.alsa_thread.playing(None, None)

            if current_packet:
                self.set_current_packet(current_packet)

            self.set_device_error(device_error)


class PythonAlsaThread(object):
    # Run on approx 10 Hz.  pyalsaaudio will hardcode the hardware buffer to
    # four periods.
    PERIOD_SIZE = 4096
    
    def __init__(self, parent, card, start_without_device,
                 channels, bytes_per_sample, rate, big_endian):
        self.log = parent.log
        self.debug = parent.debug
        self.alsa_card = card

        self.channels = channels
        self.rate = rate

        if bytes_per_sample != 2:
            raise audio.DeviceError('only supports 16-bit samples')
        
        self.bytes_per_sample = bytes_per_sample
        self.big_endian = big_endian
        

        # This should adapt to different formats, but shortcut for now
        # to standard CD PCM.
        self.alsa_period_size = self.PERIOD_SIZE

        # Buffer approx 3s of data
        self.buffer_frames = 3 * self.rate

        # Thread state attributes
        self.cond = threading.Condition()

        # Readable without lock, writing requires lock
        self.alsa_pcm = None
        self.device_error = None
        self.current_packet = None

        # Requires lock for all access

        self.buffer_periods = None # Wait until we know the period size
        self.period_bytes = None   # ditto
        
        self.data_buffer = [] # (period_frames, packet)
        self.partial_period = None

        # End of thread state attributes
        
        self.log("using PythonAlsaThread - you might get glitchy sound");

        # Try to open device
        try:
            self.debug('alsa: opening device for card: {0}', self.alsa_card)
            self.alsa_pcm = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK,
                                          mode = alsaaudio.PCM_NORMAL,
                                          card = self.alsa_card)
        except alsaaudio.ALSAAudioError, e:
            if self.start_without_device:
                self.log('alsa: error opening card {0}: {1}',
                         self.alsa_card, e)
                self.log('alsa: proceeding since start_without_device = True')
                parent.set_device_error(str(e))
            else:
                raise audio.DeviceError(e)
        
        if self.alsa_pcm:
            self._set_device_format(self.alsa_pcm)


        # Finally kick off thread
        self.play_thread = threading.Thread(target = self._play_loop, name = 'ALSA device thread')
        self.play_thread.daemon = True
        self.play_thread.start()


    def buffer_empty(self):
        """Return true if the buffer is empty
        """
        with self.cond:
            return len(self.data_buffer) == 0

    def pause(self):
        # Don't use lock here, to not risk deadlocks with
        # player thread if it is closing or opening this right now
        pcm = self.alsa_pcm
        if pcm:
            try:
                pcm.pause(1)
            except alsaaudio.ALSAAudioError, e:
                self.log('ignoring error while pausing: {0}', e)


    def resume(self):
        # Don't use lock here, to not risk deadlocks with
        # player thread if it is closing or opening this right now
        pcm = self.alsa_pcm
        if pcm:
            try:
                pcm.pause(0)
            except alsaaudio.ALSAAudioError, e:
                self.log('ignoring error while resuming: {0}', e)


    def playing(self, data, packet):
        """Wait until some of data has been added, or the player state has changed somewhat.

        When reaching the end of the stream, keep calling this with
        data == None to play out buffered data.

        Returns (stored, current_packet, device_error), where:
          stored: bytes of data added to the buffer
          current_packet: new packet being played
          device_error: any current device error, or None
        """

        with self.cond:
            # We must have some info from the device, which may not be
            # available yet
            if self.buffer_periods is None:
                self.cond.wait(1)

            if self.buffer_periods is None:
                # Still not set, so give control back to caller
                return 0, self.current_packet, self.device_error

            assert self.period_bytes is not None


            stored = 0
            device_error = self.device_error
            
            if len(self.data_buffer) >= self.buffer_periods:
                # Can't add data now, wait for it
                self.cond.wait()

            if len(self.data_buffer) >= self.buffer_periods:
                # Still can't add data, but position or device should
                # have been updated
                return 0, self.current_packet, self.device_error


            # Now we can add data to buffer

            if data is None and self.partial_period:
                # Pad final packet and push into buffer
                n = self.period_bytes - len(self.partial_period)
                assert n > 0

                self.data_buffer.append((self.partial_period + ('\0' * n), packet))
                self.partial_period = None

                # This does not increase stored, so signal thread directly
                self.cond.notifyAll()


            # Main loop, push as many periods as possible into the buffer

            while data and len(self.data_buffer) < self.buffer_periods:

                if self.partial_period:
                    # Append to left-overs from last call
                    n = self.period_bytes - len(self.partial_period)
                    assert n > 0
                    
                    # Since this may be a buffer() object we can't do +=
                    self.partial_period = self.partial_period + buffer(data, 0, n)

                    data = buffer(data, n)
                    stored += n
                    
                    if len(self.partial_period) == self.period_bytes:
                        self.data_buffer.append((self.partial_period, packet))
                        self.partial_period = None

                elif len(data) < self.period_bytes:
                    # Not enough to fill a period, store it until next call
                    self.partial_period = data
                    stored += len(data)
                    data = ''

                else:
                    # Break off a period chunk
                    self.data_buffer.append((buffer(data, 0, self.period_bytes), packet))
                    data = buffer(data, self.period_bytes)
                    stored += self.period_bytes
                    
            # Signal player thread if we stored anything
            if stored:
                self.cond.notifyAll()

            # And were done
            return stored, self.current_packet, self.device_error
    

    def discard_buffer(self):
        """Discard all buffered data, typically on aborting the stream.
        """
        with self.cond:
            del self.data_buffer[:]
            self.partial_period = None
            self.current_packet = None
            

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
                    raise audio.DeviceError(
                        "alsa: can't set S16_BE/S16_LE format, card stuck on {0}"
                        .format(v))
                

            v = pcm.setrate(self.rate)
            if v != self.rate:
                raise audio.DeviceError(
                    "alsa: can't set rate to {0}, card stuck on {1}"
                    .format(self.rate, v))
            
            v = pcm.setchannels(self.channels)
            if v != self.channels:
                raise audio.DeviceError(
                    "alsa: can't set channels to {0}, card stuck on {1}"
                    .format(self.channels, v))
            
            v = pcm.setperiodsize(self.alsa_period_size)
            if v != self.alsa_period_size:
                self.log('alsa: card refused our period size of {0}, using {1} instead',
                         self.alsa_period_size, v)
                self.alsa_period_size = v

            with self.cond:
                self.buffer_periods = int(self.buffer_frames / self.alsa_period_size)
                self.period_bytes = self.alsa_period_size * self.channels * self.bytes_per_sample

                # playing() might be waiting for this information
                self.cond.notifyAll()


        except alsaaudio.ALSAAudioError, e:
            raise audio.DeviceError(e)

    
    def _play_loop(self):
        while True:
            # Do we have an audio device?
            if self.alsa_pcm is None:
                self._reopen()

            if self.alsa_pcm is None:
                # Reopen failed.  Sleep and retry
                time.sleep(3)
                continue

            data = None

            with self.cond:
                if not self.data_buffer:
                    self.cond.wait()

                # We _should_ only be woken when there's data, but
                # let's not assume that.
                if self.data_buffer:
                    (data, packet) = self.data_buffer[0]

                    # Tell other thread we're now starting to play this packet
                    if packet != self.current_packet:
                        self.current_packet = packet
                        self.cond.notifyAll()
                    
            if data:
                assert len(data) == self.period_bytes
                # Play the data without holding the lock
                error = self._play_period(data)
                
                with self.cond:
                    if error is None:
                        # Pop period (unless it's been discarded while we're playing)
                        if self.data_buffer and self.data_buffer[0][0] is data:
                            del self.data_buffer[0]
                    else:
                        self.alsa_pcm.close()
                        self.alsa_pcm = None
                        self.device_error = error
                        self.cond.notifyAll()


    def _play_period(self, data):
        if self.alsa_swap_bytes:
            # Heavy-handed assumptions about data formats etc
            a = array.array('h', str(data))
            assert a.itemsize == 2
            a.byteswap()
            data = a.tostring()

        try:
            self.alsa_pcm.write(data)
            return None
        except alsaaudio.ALSAAudioError, e:
            self.log('alsa: error writing to device: {0}', e)
            return str(e)


    def _reopen(self):
        # Try to re-open device
        error = None
        try:
            pcm = alsaaudio.PCM(
                type = alsaaudio.PCM_PLAYBACK,
                mode = alsaaudio.PCM_NORMAL,
                card = self.alsa_card)

            self._set_device_format(pcm)

        except audio.DeviceError, e:
            error = str(e)
            self.log('alsa: failed setting format: {0}', self.alsa_card)

        except alsaaudio.ALSAAudioError, e:
            # only log if different to last error
            error = str(e)
            if self.device_error != error:
                self.debug('alsa: error reopening card {0}: {1}',
                           self.alsa_card, error)
            
        with self.cond:
            if error is None:
                self.log('alsa: successfully reopened card {0}', self.alsa_card)
                self.alsa_pcm = pcm
                self.device_error = None
            else:
                self.device_error = error

            # Tell other thread about any device errors
            self.cond.notifyAll()


try:
    from . import cod_alsa_device
    AlsaThread = cod_alsa_device.AlsaThread

except ImportError, e:
    sys.stderr.write("failed importing cod_alsa_device: {0}\n".format(e))
    import alsaaudio
    AlsaThread = PythonAlsaThread
 

