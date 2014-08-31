# codplayer - player state
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
The player state, and various ways of publishing it and reading it.
"""

from . import serialize
from . import model

class StateError(Exception): pass

class State(serialize.Serializable):
    """Player state as visible to external users.  Attributes:

    state: One of the state identifiers:
      OFF:     The player isn't running
      NO_DISC: No disc is loaded in the player
      WORKING: Disc has been loaded, waiting for streaming to start
      PLAY:    Playing disc normally
      PAUSE:   Disc is currently paused
      STOP:    Playing finished, but disc is still loaded

    disc_id: The Musicbrainz disc ID of the currently loaded disc, or None

    track: Current track being played, counting from 1. 0 if
                  stopped or no disc is loaded.

    no_tracks: Number of tracks on the disc to be played. 0 if no disc is loaded.

    index: Track index currently played. 0 for pre_gap, 1+ for main sections.

    position: Current position in track in whole seconds, counting
    from index 1 (so the pregap is negative).

    length: Length of current track in whole seconds, counting
    from index 1.

    ripping: None if not currently ripping a disc, otherwise a number
    0-100 showing the percentage done.

    error: A string giving the error state of the player, if any.
    """

    class OFF:
        valid_commands = ()

    class NO_DISC:
        valid_commands = ('quit', 'disc', 'eject')

    class WORKING:
        valid_commands = ('quit', )

    class PLAY:
        valid_commands = ('quit', 'disc', 'pause', 'play_pause',
                          'next', 'prev', 'stop', 'eject')

    class PAUSE:
        valid_commands = ('quit', 'disc', 'play', 'play_pause',
                          'next', 'prev', 'stop', 'eject')

    class STOP:
        valid_commands = ('quit', 'disc', 'play', 'play_pause',
                          'next', 'prev', 'eject')


    def __init__(self):
        self.state = self.NO_DISC
        self.disc_id = None
        self.track = 0
        self.no_tracks = 0
        self.index = 0
        self.position = 0
        self.length = 0
        self.ripping = None
        self.error = None


    def __str__(self):
        return ('{state.__name__} disc: {disc_id} track: {track}/{no_tracks} '
                'index: {index} position: {position} length: {length} ripping: {ripping} '
                'error: {error}'
                .format(**self.__dict__))


    # Deserialisation methods
    MAPPING = (
        serialize.Attr('state', enum = (OFF, NO_DISC, WORKING, PLAY, PAUSE, STOP)),
        serialize.Attr('disc_id', str),
        serialize.Attr('track', int),
        serialize.Attr('no_tracks', int),
        serialize.Attr('index', int),
        serialize.Attr('position', int),
        serialize.Attr('ripping', int),
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

    def __init__(self):
        self.state = self.INACTIVE
        self.disc_id = None
        self.progress = None
        self.error = None


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


# And here we go all Java style, including long clumsy names, but it
# does make the configuration much more useful for both server and
# clients.

class PublisherFactory(object):
    """Base class for  state publisher factories.
    """

    def publisher(self, player):
        """Return a new StatePublisher for a Player.

        This is called after the daemon forks, but before dropping privileges.
        """
        raise NotImplementedError()

    def getter(self):
        """Return a new StateGetter, or None if this publisher type doesn't
        support it.
        """
        return None

    def subscriber(self):
        """Return a new StateSubscriber, or None if this publisher type
        doesn't support it.
        """
        return None

class StatePublisher(object):
    """Base class for publishers to be used by player.Transport.

    The update methods may be called from different threads, which the
    publisher implementation must be able to handle.
    """

    def update_state(self, state):
        """Called by player.Transport when the state updates.  The publisher
        must copy the state if it needs to be stored for future reference.
        """
        raise NotImplementedError()

    def update_rip_state(self, rip_state):
        """Called by rip.Ripper when the ripping state is changed.  The
        publisher must copy the state if it needs to be stored for
        future reference.
        """
        raise NotImplementedError()

    def update_disc(self, extdisc):
        """Called by player.Transport when a new disc is loaded with a
        model.ExtDisc object, or None if no disc is loaded.  The
        publisher can keep a reference to the disc object, but not
        modify it.
        """
        raise NotImplementedError()


class StateGetter(object):
    """Base class for state getters to be used by player clients."""

    def get_state(self, timeout = None):
        """Return a State object."""
        raise NotImplementedError()

    def get_rip_state(self, timeout = None):
        """Return a RipState object"""
        raise NotImplementedError()

    def get_disc(self, timeout = None):
        """Return a model.ExtDisc object"""
        raise NotImplementedError()


class StateSubscriber(object):
    """Base class for state subscribers to be used by player clients."""

    def iter(self, timeout = None):
        """Return an iterator that will yield State, RipState or model.ExtDisc objects.

        If timeout is None it runs forever, otherwise blocks for that
        many seconds.  If timeout is 0, doesn't block at all.
        """
        raise NotImplementedError()


class FilePublisherFactory(PublisherFactory):
    """Publishes state as JSON to a file.
    """

    class FilePublisher(StatePublisher):
        def __init__(self, factory):
            self.factory = factory

        def update_state(self, state):
            serialize.save_json(state, self.factory.state_path)

        def update_rip_state(self, rip_state):
            serialize.save_json(rip_state, self.factory.rip_state_path)

        def update_disc(self, disc):
            serialize.save_json(disc, self.factory.disc_path)

    class FileGetter(StateGetter):
        def __init__(self, factory):
            self.factory = factory

        def get_state(self, timeout = None):
            try:
                return State.from_file(self.factory.state_path)
            except serialize.LoadError, e:
                raise StateError(e)

        def get_rip_state(self, timeout = None):
            try:
                return RipState.from_file(self.factory.rip_state_path)
            except serialize.LoadError, e:
                raise StateError(e)

        def get_disc(self, timeout = None):
            return serialize.load_json(model.ExtDisc, self.factory.disc_path)


    def __init__(self, state_path, rip_state_path, disc_path):
        self.state_path = state_path
        self.rip_state_path = rip_state_path
        self.disc_path = disc_path

    def publisher(self, player):
        return self.FilePublisher(self)

    def getter(self):
        return self.FileGetter(self)

