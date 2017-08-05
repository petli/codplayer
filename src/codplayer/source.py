# codplayer - audio source interface
#
# Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.


class SourceError(Exception): pass

class Source(object):
    """Abstract base class representing a source of audio packets.
    """

    def initial_state(self, state):
        """Add any source-specific information to the inital state when this
        source starts playing.
        """
        return state

    def iter_packets(self, track_number, packet_rate):
        """Iterate over audio packets from this source, starting at
        TRACK_NUMBER (counting from 0) and running at approximately
        PACKET_RATE Hz.

        Raise SourceError if running into errors, and just return
        normally at the end of the stream.

        The iterator can generate None if there isn't a packet ready
        after a delay to give control back to the transport.
        """
        raise NotImplementedError()
