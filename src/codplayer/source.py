# codplayer - audio source interface
#
# Copyright 2014-2018 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.


class SourceError(Exception): pass

class Source(object):
    """Abstract base class representing a source of audio packets.
    """

    @property
    def disc(self):
        return None

    @property
    def pausable(self):
        """True if this is a source that can be paused.  If False
        the source will be stopped instead of paused.
        """
        return True

    def initial_state(self, state):
        """Add any source-specific information to the inital state when this
        source starts playing.
        """
        return state

    def iter_packets(self):
        """Iterate over audio packets from this source.

        Raise SourceError if running into errors, and just return
        normally at the end of the stream.

        The iterator can generate None if there isn't a packet ready
        after a delay to give control back to the transport.
        """
        raise NotImplementedError()

    def stalled(self):
        """Called if the playback is stalled because no packets have been
        delivered for a while.  The source can use this as a signal
        that it might need to reset itself.
        """
        pass

    def stopped(self):
        """Called when playback of the source has been stopped.
        """
        pass

    def next_source(self, state):
        """Called in response to the next command.  Given the current state
        the source should either return itself to indicate no change,
        return a new source, or return None to signal that playback
        should stop.
        """
        return self

    def prev_source(self, state):
        """Same as next_source(), but for the other direction.
        """
        return self
