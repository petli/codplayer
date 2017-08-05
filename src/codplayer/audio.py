# codplayer - audio packet generator
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.


class AudioPacket(object):
    """A packet of audio data.

    It has the following attributes:

    context: the current context count, set by the source thread

    data: sample data

    format: the sample format, typically model.PCM

    flags: currently only one possible:
      - PAUSE_AFTER
    """

    PAUSE_AFTER = 0x01

    def __init__(self, format, flags = 0):
        self.context = None
        self.data = None
        self.format = format
        self.flags = flags

    def update_state(self, state):
        """Called when this packet has just been played to update the player state.

        Parameter state holds the current State object, and a new
        State object should only be returned if anything has changed
        since that, otherwise return None to keep the current state.
        """
        raise NotImplementedError()
