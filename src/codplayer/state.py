# codplayer - player state
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
The player states and a subscriber for state updates.
"""

import time

from . import zerohub
from . import serialize
from . import model

class StateError(Exception): pass

class BaseInfo(serialize.Serializable):
    def __init__(self, title = None, artist = None):
        self.title = title
        self.artist = artist

    def __str__(self):
        return u'{title}/{artist}'.format(**self.__dict__)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False

        if self is other:
            return True

        return self.title == other.title and self.artist == other.artist

    def __ne__(self, other):
        return not self == other


    MAPPING = (
        serialize.Attr('title', serialize.str_unicode),
        serialize.Attr('artist', serialize.str_unicode),
    )

class SongInfo(BaseInfo):
    pass

class AlbumInfo(BaseInfo):
    pass


class State(serialize.Serializable):
    """Player state as visible to external users.  Attributes:

    state: One of the state identifiers:
      OFF:     The player isn't running
      NO_DISC: No disc is loaded in the player
      WORKING: Disc has been loaded, waiting for streaming to start
      PLAY:    Playing disc normally
      PAUSE:   Disc is currently paused
      STOP:    Playing finished, but disc is still loaded

    disc_id: The Musicbrainz disc ID of the currently playing disc, or None

    source_disc_id: The source disc ID that triggered the current
    play, which may be different from disc_id (e.g. for aliased
    discs).  Set to `None` if the disc isn't linked to another one.

    stream: Name of current radio stream, or None

    track: Current track being played, counting from 1. 0 if
                  stopped or no disc is loaded.

    no_tracks: Number of tracks on the disc to be played. 0 if no disc is loaded.

    index: Track index currently played. 0 for pre_gap, 1+ for main sections.

    position: Current position in track in whole seconds, counting
    from index 1 (so the pregap is negative).

    length: Length of current track in whole seconds, counting
    from index 1.

    album_info: Information about the album of the current song, if
    known.

    song_info: Information about the current song, if known.

    error: A string giving the error state of the player, if any.
    """

    class OFF: pass
    class NO_DISC: pass
    class WORKING: pass
    class PLAY: pass
    class PAUSE: pass
    class STOP: pass

    def __init__(self, old_state=None, **kwargs):
        self.state = State.NO_DISC
        self.disc_id = None
        self.source_disc_id = None
        self.stream = None
        self.track = 0
        self.no_tracks = 0
        self.index = 0
        self.position = 0
        self.length = 0
        self.album_info = None
        self.song_info = None
        self.error = None

        # Copy or update attributes from previous state or arguments
        for m in self.MAPPING:
            if m.name in kwargs:
                setattr(self, m.name, kwargs[m.name])
            elif old_state:
                setattr(self, m.name, getattr(old_state, m.name))

    def __str__(self):
        return (u'{state.__name__} disc: {disc_id} source: {source_disc_id} stream: {stream} '
                u'track: {track}/{no_tracks} '
                u'index: {index} position: {position} length: {length} '
                u'album: {album_info} song: {song_info} '
                u'error: {error}'
                .format(**self.__dict__)).encode('utf-8')

    MAPPING = (
        serialize.Attr('state', enum = (OFF, NO_DISC, WORKING, PLAY, PAUSE, STOP)),
        serialize.Attr('disc_id', str),
        serialize.Attr('source_disc_id', str, optional = True),
        serialize.Attr('stream', str),
        serialize.Attr('track', int),
        serialize.Attr('no_tracks', int),
        serialize.Attr('index', int),
        serialize.Attr('position', int),
        serialize.Attr('length', int),
        serialize.Attr('album_info', AlbumInfo, optional = True),
        serialize.Attr('song_info', SongInfo, optional = True),
        serialize.Attr('error', serialize.str_unicode),
        )


class RipState(serialize.Serializable):
    """Ripping state as visible to external users.  Attributes:

    state: One of the following identifiers:
      INACTIVE:  No ripping is currently taking place
      AUDIO:     Audio data is being read
      TOC:       TOC is being read

    disc_id: The Musicbrainz disc ID of the currently ripped disc, or None

    progress: Percentage of 0-100 for current phase, or None if not
    known or not applicable

    error: The last ripping error, if any.
    """

    class INACTIVE: pass
    class AUDIO: pass
    class TOC: pass

    def __init__(self, state = INACTIVE, disc_id = None,
                 progress = None, error = None):
        self.state = state
        self.disc_id = disc_id
        self.progress = progress
        self.error = error


    def __str__(self):
        return ('{state.__name__} disc: {disc_id} progress: {progress} error: {error}'
                .format(**self.__dict__))


    # Deserialisation methods
    MAPPING = (
        serialize.Attr('state', enum = (INACTIVE, AUDIO, TOC)),
        serialize.Attr('disc_id', str),
        serialize.Attr('progress', int),
        serialize.Attr('error', serialize.str_unicode),
        )



class StateClient(object):
    """Subscribe to state published on a zerohub.Topic."""

    def __init__(self, channel, io_loop = None,
                 on_state = None, on_rip_state = None, on_disc = None,
                 max_age_seconds = None):

        """Subscribe to the provided channel, using the provided IO loop or the default one.

        The event callbacks will be called with the deserialised
        State, RipState or Disc object as a single argument.

        If max_age_seconds is set messages older that that will be
        discarded without being parsed.
        """

        subscriptions = {}
        if on_state:
            subscriptions['state'] = (lambda receiver, msg: self._parse_message(msg, State, on_state))
        if on_rip_state:
            subscriptions['rip_state'] = (lambda receiver, msg: self._parse_message(msg, RipState, on_rip_state))
        if on_disc:
            subscriptions['disc'] = (lambda receiver, msg: self._parse_message(msg, model.ExtDisc, on_disc))

        self._max_age_seconds = max_age_seconds

        self._reciever = zerohub.Receiver(
            channel, io_loop = io_loop, callbacks = subscriptions, )

    def close(self):
        if self._reciever:
            self._reciever.close()
            self._reciever = None

    def _parse_message(self, msg, cls, callback):
        if len(msg) < 2:
            raise StateError('zeromq: missing message parts: {0}'.format(msg))

        if len(msg) > 2 and self._max_age_seconds:
            send_time = float(msg[2])
            age = time.time() - send_time
            if age > self._max_age_seconds:
                return

        try:
            obj = serialize.load_jsons(cls, msg[1])
        except serialize.LoadError, e:
            raise StateError('zeromq: malformed message object: {0}'.format(msg))

        callback(obj)
