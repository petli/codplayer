# codplayer - PCM disc audio source
#
# Copyright 2014-2018 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import os
import time
import errno
import threading

from .. import audio
from ..source import *
from ..state import State

class PCMDiscSource(Source):
    """Generate audio packets from a database disc in PCM format.
    """

    def __init__(self, player, disc, track_number, is_ripping):
        super(PCMDiscSource, self).__init__()

        self._player = player
        self._disc = disc
        self._track_number = track_number
        self.log = player.log
        self.debug = player.debug

        # Due to the Big Interpreter Lock we probably don't need any
        # thread signalling at all for these simple flags, but let's
        # play it nice.

        if is_ripping:
            self.is_ripping = threading.Event()
            self.is_ripping.set()
        else:
            self.is_ripping = None

        # Construct full path to data file
        db_id = self._player.db.disc_to_db_id(self.disc.disc_id)
        self.path = os.path.join(
            self._player.db.get_disc_dir(db_id),
            self.disc.data_file_name)

        self.audio_file = None


    @property
    def disc(self):
        return self._disc

    # TODO: this method is not called. Was this logic moved into player.Transport
    # and should it thus be removed from here?
    def rip_finished(self):
        """Call to inform that the any concurrent ripping process is finished."""

        if self.is_ripping:
            self.is_ripping.clear()


    def initial_state(self, state):
        return State(state,
                     source = 'disc:{}'.format(self.disc.disc_id),
                     disc_id = self.disc.disc_id,
                     source_disc_id = self.disc.source_disc_id,
                     track = self._track_number + 1,
                     no_tracks = len(self.disc.tracks))


    def iter_packets(self):
        self.debug('generating packets for {0} starting at track {1}',
                   self.disc, self._track_number)

        # Retry opening file if the ripping process is in progress
        # and might not have had time to create it yet

        while self.audio_file is None:
            try:
                self.debug('opening file {0}', self.path)
                self.audio_file = open(self.path, 'rb')
            except IOError, e:
                if e.errno == errno.ENOENT and self.is_ripping and self.is_ripping.is_set():
                    time.sleep(1)
                    # Give transport control
                    yield None
                else:
                    raise SourceError('error opening file {0}: {1}'.format(self.path, e))

        # Iterate over all packets, reading data into them

        for p in PCMDiscAudioPacket.iterate(self.disc, self._track_number):

            try:
                self._read_data_into_packet(p)
            except IOError, e:
                raise SourceError('error reading from file {0}: {1}'.format(self.path, e))

            # Send out packet to transport
            yield p

            if p.flags & p.PAUSE_AFTER:
                # Playback will effectively stop here, so remember the track number to start
                # playing at again and return to signal end of stream
                self.debug('disc pausing after track {}, stopping for now', p.track_number + 1)
                self._track_number = p.track_number + 1
                return

        # Reset this so hitting PLAY again in STOP will start from the beginning of the disc
        self._track_number = 0


    def next_source(self, state):
        if state.state == State.STOP:
            self.log('disc playing from STOP on command next')
            return self._new_source_track(0)

        elif state.state in (State.PLAY, State.PAUSE):
            # Since state.track is 1-based, comparison and next
            # track here don't need to add 1
            if state.track < state.no_tracks:
                self.log('disc skipping to next track')
                return self._new_source_track(state.track)
            else:
                self.log('disc stopping on skipping past last track')
                return None

        else:
            self.log('disc ignoring next in state {}', state.state)
            return self


    def prev_source(self, state):
        if state.state == State.STOP:
            self.log('disc playing from STOP on command prev')
            return self._new_source_track(len(self._disc.tracks) - 1)

        elif state.state in (State.PLAY, State.PAUSE):
            # Calcualte which track is next (first track in state is 1)
            assert state.track >= 1

            # If the track position is within the first two seconds or
            # the pregap, skip to the previous track.  Otherwise replay
            # this track from the start

            if state.position < 2:
                self.log('disc skipping to previous track')
                tn = state.track - 1
            else:
                self.log('disc restarting current track')
                tn = state.track

            if tn > 0:
                return self._new_source_track(tn - 1)
            else:
                self.log('disc stopping on skipping past first track')
                return None

        else:
            self.log('disc ignoring prev in state {}', state.state)
            return self


    def _new_source_track(self, track):
        return PCMDiscSource(self._player, self._disc, track, self.is_ripping and self.is_ripping.is_set())


    def _read_data_into_packet(self, p):
        """Helper method for populating data into packet P."""

        length = p.length * self.disc.audio_format.bytes_per_frame

        if p.file_pos is None:
            # Silence, so send on null bytes to player
            p.data = '\0' * length

        else:
            file_pos = p.file_pos * self.disc.audio_format.bytes_per_frame
            self.audio_file.seek(file_pos)

            p.data = self.audio_file.read(length)
            length -= len(p.data)
            file_pos += len(p.data)

            # If we didn't get all data, iterate with a timeout until
            # it's all been read or the ripping process has stopped.
            # This is not very efficient, and there's a small race
            # condition at the end of the disc, but this should be
            # very rare so keep it unoptimised for now.

            while length > 0 and self.is_ripping and self.is_ripping.is_set():
                time.sleep(1)

                self.audio_file.seek(file_pos)
                d = self.audio_file.read(length)

                length -= len(d)
                file_pos += len(d)

                p.data += d

            # Still didn't get all data, treat it as an exception
            if length > 0:
                raise SourceError('unexpected end of file, expected at least {0} bytes'
                                  .format(length))


class PCMDiscAudioPacket(audio.AudioPacket):
    """A packet of PCM disc audio data coming from a single track and index.

    It has the following attributes in addition to AudioPacket (all
    positions and lengths count audio frames, as usual):

    disc: a model.DbDisc object

    track: a model.DbTrack object

    track_number: the number of the track in the play order, counting
    from 0 (and not always equal to track.number - 1, e.g. when randomising
    play order)

    index: the track index counting from 0

    abs_pos: the track position from the start of index 0

    rel_pos: the track position from the start of index 1

    file_pos: the file position for the first track, or None if the
    packet should be silence

    length: number of frames in the packet

    data: sample data

    format: the sample format, typically model.PCM

    flags: currently only one possible:
      - PAUSE_AFTER

    """

    PACKETS_PER_SECOND = 5

    def __init__(self, disc, track, track_number, abs_pos, length, flags = 0):
        super(PCMDiscAudioPacket, self).__init__(disc.audio_format, flags)

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


    def __repr__(self):
        return '<PCMDiscAudioPacket: {0.disc.disc_id} track {0.track_number} abs_pos {0.abs_pos}>'.format(self)


    def update_state(self, state):
        pos = int(self.rel_pos / self.format.rate)

        # New track
        if (state.track != self.track_number + 1
            or state.index != self.index):
            return State(state,
                         track = self.track_number + 1,
                         index = self.index,
                         position = pos,
                         length = int((self.track.length - self.track.pregap_offset)
                                      / self.format.rate))

        # Position changed by a whole second
        if pos != state.position:
            return State(state, position = pos)

        # No change
        return None


    @classmethod
    def iterate(cls, disc, track_number):
        """Iterate over DISC, splitting it into packets starting at
        TRACK_NUMBER index 1.

        This call will ensure that no packets cross a track or pregap
        boundary, and will also obey any edits to the disc.

        It will not, however, read any samples from disc, just tell the
        calling code what to read.
        """

        assert track_number >= 0 and track_number < len(disc.tracks)

        track = disc.tracks[track_number]

        packet_frame_size = (
            disc.audio_format.rate / cls.PACKETS_PER_SECOND)

        # Mock up a packet that ends at the start of index 1, so the
        # first packet generated starts at that position
        p = cls(disc, track, track_number, track.pregap_offset, 0)

        while True:
            # Calculate offsets of next packet
            abs_pos = p.abs_pos + p.length

            if abs_pos < track.pregap_offset:
                length = min(track.pregap_offset - abs_pos, packet_frame_size)
            else:
                length = min(track.length - abs_pos, packet_frame_size)

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
                flags = 0
                if (track.pause_after
                    and abs_pos + length == track.length
                    and track_number + 1 < len(disc.tracks)):
                    flags |= p.PAUSE_AFTER

                p = cls(disc, track, track_number, abs_pos, length, flags)
                yield p
