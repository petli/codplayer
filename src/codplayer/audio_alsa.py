# codplayer - base class for the audio devices
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import array

import time

from . import audio, model

class PythonAlsaDevice(object):
    # Run on approx 10 Hz.  pyalsaaudio will hardcode the hardware buffer to
    # four periods.
    PERIOD_SIZE = 4096
    
    def __init__(self, parent, card_name, start_without_device):
        self.log = parent.log
        self.debug = parent.debug
        self.set_device_error = parent.set_device_error
        self.set_current_packet = parent.set_current_packet
        self.alsa_card = card_name
        self.start_without_device = start_without_device

        # This should adapt to different formats, but shortcut for now
        # to standard CD PCM.
        self.alsa_period_size = self.PERIOD_SIZE

        self.alsa_pcm = None

        # Open device
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
                self.set_device_error(str(e))
            else:
                raise audio.DeviceError(e)
        
        if self.alsa_pcm:
            self.set_device_format()


    def set_device_format(self):
        # Set format to big endian 44100 Hz to match CDR format,
        # fallbacking to little endian if necessary.

        # FIXME: This really should adapt to whatever audio is sent
        # the device way by the streamer.

        try:
            v = self.alsa_pcm.setformat(alsaaudio.PCM_FORMAT_S16_BE)

            # Card accepts CD byte order
            if v == alsaaudio.PCM_FORMAT_S16_BE:
                self.alsa_swap_bytes = False

            # Try byte swapped order instead
            else:
                self.debug('alsa: swapping bytes')
                self.alsa_swap_bytes = True

                v = self.alsa_pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
                if v != alsaaudio.PCM_FORMAT_S16_LE:
                    raise audio.DeviceError(
                        "alsa: can't set S16_BE/S16_LE format, card stuck on {0}"
                        .format(v))
                

            v = self.alsa_pcm.setrate(model.PCM.rate)
            if v != model.PCM.rate:
                raise audio.DeviceError(
                    "alsa: can't set rate to {0}, card stuck on {1}"
                    .format(model.PCM.rate, v))
            
            v = self.alsa_pcm.setchannels(model.PCM.channels)
            if v != model.PCM.channels:
                raise audio.DeviceError(
                    "alsa: can't set channels to {0}, card stuck on {1}"
                    .format(model.PCM.channels, v))
            
            v = self.alsa_pcm.setperiodsize(self.alsa_period_size)
            if v != self.alsa_period_size:
                self.log('alsa: card refused our period size of {0}, using {1} instead',
                         self.alsa_period_size, v)
                self.alsa_period_size = v

        except alsaaudio.ALSAAudioError, e:
            raise audio.DeviceError(e)

    
    def pause(self):
        if self.alsa_pcm:
            self.alsa_pcm.pause(1)


    def resume(self):
        if self.alsa_pcm:
            self.alsa_pcm.pause(0)


    def play_stream(self, stream):
        # Collect audio packets into chunks matching the ALSA period
        # size.  This code is a prime candidate for becoming more
        # efficient.

        data = ''
        period_bytes = self.alsa_period_size * model.PCM.bytes_per_frame
        
        first_packet = True
        for p in stream:

            # When starting playing, set the packet directly as
            # the buffer is likely empty
            if first_packet:
                self.set_current_packet(p)
                first_packet = False

            
            # Do we have an audio device?
            if self.alsa_pcm is None:
                self.try_reopen()

            if self.alsa_pcm is None:
                # Reopen failed.  Sacrifice this packet and sleep a while
                time.sleep(3)
                continue

            if self.alsa_swap_bytes:
                # More heavy-handed assumptions about data formats etc
                a = array.array('h', p.data)
                assert a.itemsize == 2
                a.byteswap()
                data += a.tostring()
            else:
                data += p.data

            while len(data) >= period_bytes:
                try:
                    self.alsa_pcm.write(buffer(data, 0, period_bytes))
                    data = data[period_bytes:]
                except alsaaudio.ALSAAudioError, e:
                    self.log('alsa: error writing to device: {0}', e)
                    self.set_device_error(str(e))
                    self.alsa_pcm = None
                    data = ''
                                    
            # When all that went into the device buffer, it's close
            # enough to this packet position to update the state
            self.set_current_packet(p)

        if data:
            # Still some straggling frames to play, so round out to a whole period
            data += '\0' * (period_bytes - len(data))
            assert len(data) == period_bytes
            self.alsa_pcm.write(data)


    def try_reopen(self):
        # Try to re-open device
        try:
            self.debug('alsa: retrying opening device for card: {0}',
                       self.alsa_card)

            self.alsa_pcm = alsaaudio.PCM(
                type = alsaaudio.PCM_PLAYBACK,
                mode = alsaaudio.PCM_NORMAL,
                card = self.alsa_card)

        except alsaaudio.ALSAAudioError, e:
            self.debug('alsa: error reopening card {0}: {1}',
                         self.alsa_card, e)
            self.set_device_error(str(e))
            return

        try:
            self.set_device_format()
        except alsa.DeviceError, e:
            self.log('alsa: failed setting format: {0}', self.alsa_card)
            self.alsa_pcm = None
            return

        self.log('alsa: successfully reopened card {0}', self.alsa_card)
        self.set_device_error(None)



import alsaaudio
AlsaDeviceImpl = PythonAlsaDevice


class AlsaDevice(audio.ThreadDevice):
    """ALSA sound playback device.

    This will use a C module when available, otherwise fall back on
    the PythonAlsaDevice class that uses pyalsadevice.
    """

    def __init__(self, player, config):
        super(AlsaDevice, self).__init__(player, config)

        self.alsa_pcm = AlsaDeviceImpl(
            self,
            self.config.alsa_card,
            self.config.start_without_device)
        

    def pause(self):
        self.alsa_pcm.pause()

    def resume(self):
        self.alsa_pcm.resume()

    def thread_play_stream(self, stream):
        self.alsa_pcm.play_stream(stream)
        
