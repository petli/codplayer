# codplayer - base class for the audio devices
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import array

import alsaaudio

from . import audio, model

class AlsaDevice(audio.ThreadDevice):
    """ALSA sound playback device.

    For now it uses pyalsaaudio which might run into all sorts of
    trouble with Python threading.  When that turns into a problem,
    this should migrate to a custom C module that handles the ALSA
    thread.
    """

    # Run on approx 10 Hz.  pyalsaaudio will hardcode the hardware buffer to
    # four periods.
    PERIOD_SIZE = 4096
    
    def __init__(self, player, config):
        super(AlsaDevice, self).__init__(player, config)

        self.alsa_card = config.alsa_card

        # This should adapt to different formats, but shortcut for now
        # to standard CD PCM.
        self.alsa_period_size = self.PERIOD_SIZE

        # Open device
        try:
            self.debug('alsa: opening device for card: {0}', self.alsa_card)
            self.alsa_pcm = alsaaudio.PCM(type = alsaaudio.PCM_PLAYBACK,
                                          mode = alsaaudio.PCM_NORMAL,
                                          card = self.alsa_card)
        except alsaaudio.ALSAAudioError, e:
            raise audio.DeviceError(e)
        
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
        self.alsa_pcm.pause(1)

    def resume(self):
        self.alsa_pcm.pause(0)


    def thread_play_stream(self, stream):
        # Collect audio packets into chunks matching the ALSA period
        # size.  This code is a prime candidate for becoming more
        # efficient.

        data = ''
        period_bytes = self.alsa_period_size * model.PCM.sample_bytes
        
        for p in stream:
            if self.alsa_swap_bytes:
                # More heavy-handed assumptions about data formats etc
                a = array.array('h', p.data)
                assert a.itemsize == 2
                a.byteswap()
                data += a.tostring()
            else:
                data += p.data

            while len(data) >= period_bytes:
                self.alsa_pcm.write(buffer(data, 0, period_bytes))
                data = data[period_bytes:]
                                    
            # When all that went into the device buffer, it's close
            # enough to this packet position to update the state
            self.set_current_packet(p)

        if data:
            # Still some straggling frames to play, so round out to a whole period
            data += '\0' * (period_bytes - len(data))
            assert len(data) == period_bytes
            self.alsa_pcm.write(data)
