# codplayer - audio packet and the base classes for the audio devices
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import threading
import Queue

class DeviceError(Exception): pass

class StreamAbort(Exception):
    """Base class for cases where the streaming is aborted before
    reaching the end of the disc.  If possible, the audio device
    should drop any audio buffered in the device when this is raised
    by the stream iterator.
    """
    pass

class StreamSkipAbort(StreamAbort):
    """Raised by the stream iterator when the playback was aborted due
    to skipping among tracks.  In this case the audio device should
    not let get_current_packet() return return None but the last
    packet played before being aborted.
    """
    pass


class Device(object):
    """Abstract sound device base class."""
    
    def __init__(self, player, config):
        """Create a new audio device interface to be used by PLAYER,
        using settings from CONFIG.
        """
        
        self.player = player
        self.log = player.log
        self.debug = player.debug

    def start(self):
        """Do anything necessary to start the device (e.g. starting a thread)."""
        pass

    def play_stream(self, stream):
        """Play a new audio stream.  STREAM is an iterator that will
        produce AudioPacket objects.
        """
        raise NotImplementedError()

    def pause(self):
        """Pause the player."""
        raise NotImplementedError()

    def resume(self):
        """Resume the player after pausing."""
        raise NotImplementedError()


    def get_current_packet(self):
        """Return the current packet being played (or an approximation
        of it), or None if the stream has stopped.
        """
        raise NotImplementedError()


    def get_fds(self):
        """Return a list of all file descriptors open for the device."""
        return []


class ThreadDevice(Device):
    """Common base for audio devices that implement the sound playing
    in a separate thread (most likely all of them).
    """

    def __init__(self, player, config):
        super(ThreadDevice, self).__init__(player, config)
        
        self.stream_queue = Queue.Queue()

        self.thread = threading.Thread(target = self.run_thread)
        self.thread.daemon = True
        
        # Keep track of the last packet played by the audio device.
        # Given Python's Big Interpreter Lock we might not really need
        # the lock, but let's play nicely.
        self.current_packet_lock = threading.Lock()
        self.current_packet = None


    def start(self):
        self.thread.start()


    def play_stream(self, stream):
        self.stream_queue.put(stream)


    def run_thread(self):
        self.debug('{0}: audio device thread started', self.thread.name)

        try:
            while True:
                stream = self.stream_queue.get()

                self.debug('{0}: playing new stream', self.thread.name)

                try:
                    self.thread_play_stream(stream)
                except StreamSkipAbort:
                    self.debug('{0}: stream aborted due to skipping tracks', self.thread.name)
                except StreamAbort, e:
                    self.debug('{0}: stream aborted: {1} ', self.thread.name, e)
                    self.set_current_packet(None)
                else:
                    self.set_current_packet(None)

        finally:
            self.debug('{0}: audio device thread stopped (likely on error)',
                       self.thread.name)
        

    def get_current_packet(self):
        with self.current_packet_lock:
            return self.current_packet

    #
    # Methods for sub-classes
    #
            
    def thread_play_stream(self, stream):
        """Play a new stream in the thread."""
        raise NotImplementedError()


    def set_current_packet(self, packet):
        with self.current_packet_lock:
            self.current_packet = packet


class AudioPacket(object):
    """A packet of audio data coming from a single track and index.

    It has the following attributes (all positions and lengths count
    samples, as usual):
    
    disc: a model.Disc object 

    track: a model.Track object 

    track_number: the number of the track in the play order, counting
    from 0 (and not always equal to track.number - 1, e.g. when randomising
    play order)
    
    index: the track index counting from 0

    abs_pos: the track position from the start of index 0

    rel_pos: the track position from the start of index 1

    file_pos: the file position for the first track, or None if the
    packet should be silence

    length: number of samples in the packet

    data: sample data
    """

    def __init__(self, disc, track, track_number, abs_pos, length):
        self.disc = disc
        self.track = track
        self.track_number = track_number

        assert abs_pos + length <= track.length

        if abs_pos < track.pregap_offset:
            self.index = 0
        else:
            self.index = 1

            for index_pos in track.index:
                if abs_pos < index_pos:
                    break
                self.index += 1

        self.abs_pos = abs_pos
        self.rel_pos = abs_pos - track.pregap_offset
        self.length = length

        if abs_pos < track.pregap_silence:
            # In silent part of pregap that's not in the audio file
            assert abs_pos + length <= track.pregap_silence
            self.file_pos = None
        else:
            self.file_pos = track.file_offset + abs_pos - track.pregap_silence

        self.data = None

    @classmethod
    def iterate(cls, disc, track_number, packets_per_second):
        """Iterate over DISC, splitting it into packets starting at
        TRACK_NUMBER index 1.

        The maximum size of the packets returned is controlled by
        PACKETS_PER_SECOND.

        This call will ensure that no packets cross a track or pregap
        boundary, and will also obey any edits to the disc.

        It will not, however, read any samples from disc, just tell the
        calling code what to read.
        """

        assert track_number >= 0 and track_number < len(disc.tracks)

        track = disc.tracks[track_number]

        packet_sample_size = (
            disc.sample_format.rate / packets_per_second)

        # Mock up a packet that ends at the start of index 1, so the
        # first packet generated starts at that position
        p = cls(disc, track, track_number, track.pregap_offset, 0)

        while True:
            # Calculate offsets of next packet
            abs_pos = p.abs_pos + p.length

            if abs_pos < track.pregap_offset:
                length = min(track.pregap_offset - abs_pos, packet_sample_size)
            else:
                length = min(track.length - abs_pos, packet_sample_size)

            assert length >= 0

            if length == 0:
                # Reached end of track, switch to next.  Simplify this
                # code by generating a dummy packet for the next
                # iteration to work on (but don't yield it!)

                track_number += 1

                try:
                    track = disc.tracks[track_number]
                except IndexError:
                    # That was the last track, no more packets
                    return

                p = cls(disc, track, track_number, 0, 0)                

            else:
                # Generate next packet
                p = cls(disc, track, track_number, abs_pos, length)
                yield p

    
