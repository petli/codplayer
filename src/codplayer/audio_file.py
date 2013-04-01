# codplayer - audio packet and the base classes for the audio devices
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import time

from . import audio

class FileDevice(audio.ThreadDevice):
    """Audio "device" that saves streamed audio to a file.  Intended for testing.
    """
    
    def __init__(self, player, config):
        super(FileDevice, self).__init__(player, config)

        self.file_play_speed = config.file_play_speed

    def thread_play_stream(self, stream):
        f = open('stream_{0}.cdr'.format(time.time()), 'wb')

        for p in stream:
            self.set_current_packet(p)
            f.write(p.data)

            if self.file_play_speed > 0:
                # Simulate real playing by sleeping 
                time.sleep(float(p.length) / (p.disc.sample_format.rate
                                              * self.file_play_speed)

        f.close()
