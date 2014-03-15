# codplayer - audio sink, typically sound card
#
# Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes implementing various audio packet sinks.
"""

import time

class SinkError(Exception): pass

class Sink(object):
    """Abstract base class for audio sinks (i.e. typically sound devices).
    """

    def __init__(self, player):
        pass

    def pause(self):
        """Pause the sink playback.  Return True if it could be paused.

        This method may be called from any thread, but will not
        overlap calls to resume(), stop() or start().
        """
        return False


    def resume(self):
        """Resume the sink after pausing.

        This method may be called from any thread, but will not
        overlap calls to pause(), stop() or start().
        """
        pass


    def stop(self):
        """Stop playing, discarding any buffered audio.

        This method may be called from any thread, but will not
        overlap calls to pause(), resume() or start().
        """
        pass


    def start(self, format):
        """(Re)start the sink to play new audio of type FORMAT
        (typically model.PCM).  This is always called before the first
        add_packet() after creating the sink or a call to stop().

        This method is only called from the Transport sink thread, and
        will not overlap calls to pause(), resume() or start().
        """
        pass


    def add_packet(self, packet, offset):
        """Add packet.data, starting at offset, to the sink.

        Returns (stored, current_packet, error), where:
          stored: bytes of data added to the buffer
          current_packet: current packet being played by the sink
          error: any current sink error, or None

        This method is only called from the Transport sink thread.
        """
        raise NotImplementedError()


    def drain(self):
        """Drain any data buffered in the sink.

        Return None if all data has been played and any buffers are
        empty.

        Otherwise return (current_packet, error), where:
          current_packet: current packet being played by the sink
          error: any current sink error, or None

        This method is only called from the Transport sink thread.
        """
        return None


class FileSink(Sink):
    """A simple sink to a file, mainly for testing purposes.
    """

    def __init__(self, player):
        self.file_play_speed = player.cfg.file_play_speed
        self.file_paused = False
        self.file = None
        self.format = None

    def pause(self):
        self.file_paused = True
        return True
        
    def resume(self):
        self.file_paused = False

    def stop(self):
        self.file_paused = False
        self.file = None
        self.format = None

    def start(self, format):
        self.file = open('stream_{0}.cdr'.format(time.time()), 'wb')
        self.format = format
        
    def add_packet(self, packet, offset):
        f = self.file
        format = self.format
        if not (f and format):
            # stopped in flight
            return 0, packet, None

        # Simulate pausing
        while self.file_paused:
            time.sleep(1)
                
        f.write(buffer(packet.data, offset))

        if self.file_play_speed > 0:
            # Simulate real playing by sleeping 
            time.sleep(float(packet.length) / (format.rate
                                               * self.file_play_speed))

        return len(packet.data), packet, None


class AlsaSink(Sink):
    """ALSA sink, relying on a C or Python implementation behind it.
    It unpacks the objects passed in somewhat to make the C
    implementation simpler.
    """

    def __init__(self, player):
        try:
            from .c_alsa_sink import CAlsaSink as AlsaSinkImpl
        except ImportError, e:
            player.debug('error importing c_alsa_sink: {0}', e)
            from .py_alsa_sink import PyAlsaSink as AlsaSinkImpl

        self.impl = AlsaSinkImpl(player,
                                 player.cfg.alsa_card,
                                 player.cfg.start_without_device,
                                 player.cfg.log_performance)

    def pause(self):
        return self.impl.pause()

    def resume(self):
        self.impl.resume()

    def stop(self):
        self.impl.stop()

    def start(self, format):
        self.impl.start(format.channels, format.bytes_per_sample, format.rate, format.big_endian)

    def add_packet(self, packet, offset):
        return self.impl.add_packet(buffer(packet.data, offset), packet)

    def drain(self):
        return self.impl.drain()


SINKS = {
    'file': FileSink,
    'alsa': AlsaSink,
    }
