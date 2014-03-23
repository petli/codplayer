# codplayer - audio packet generator
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.


class AudioPacket(object):
    """A packet of audio data coming from a single track and index.

    It has the following attributes (all positions and lengths count
    audio frames, as usual):
    
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
    """

    def __init__(self, disc, track, track_number, abs_pos, length):
        self.disc = disc
        self.track = track
        self.track_number = track_number

        self.format = disc.audio_format
        
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


    def __repr__(self):
        return '<AudioPacket: {0.disc.disc_id} track {0.track_number} abs_pos {0.abs_pos}>'.format(self)


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

        packet_frame_size = (
            disc.audio_format.rate / packets_per_second)

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
                p = cls(disc, track, track_number, abs_pos, length)
                yield p

    
