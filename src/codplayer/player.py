# codplayer - player core
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes implementing the player core.

The unit of time in all objects is one audio frame.
"""

import sys
import os
import pwd
import grp
import errno
import subprocess
import time
import threading
import Queue
import traceback
import copy

from . import serialize
from . import db
from . import model
from . import source
from . import sink
from . import rip
from .state import State, RipState
from .command import CommandError
from . import zerohub
from . import full_version

class PlayerError(Exception):
    pass


class Player(object):
    def __init__(self, cfg, mq_cfg, database, log_file):
        self.cfg = cfg
        self.mq_cfg = mq_cfg
        self.db = database
        self.log_file = log_file
        self.log_debug = True

        self.transport = None
        
        self.ripper = None

        # Figure out which IDs to run as, if any
        self.uid = None
        self.gid = None

        if self.cfg.user:
            try:
                pw = pwd.getpwnam(self.cfg.user)
                self.uid = pw.pw_uid
                self.gid = pw.pw_gid
            except KeyError:
                raise PlayerError('unknown user: {0}'.format(self.cfg.user))

        if self.cfg.group:
            if not self.cfg.user:
                raise PlayerError("can't set group without user in config")
            
            try:
                gr = grp.getgrnam(self.cfg.group)
                self.gid = gr.gr_gid
            except KeyError:
                raise PlayerError('unknown group: {0}'.format(self.cfg.user))


        if self.cfg.log_performance:
            self.audio_streamer_perf_log = open('/tmp/cod_audio_streamer.log', 'wt')
        else:
            self.audio_streamer_perf_log = None
            
        
    def run(self):
        self.log('-' * 60)
        self.log('starting {}', full_version())

        try:
            # Set up messaging endpoints before dropping privs, in case
            # privileged ports are used
            self.io_loop = zerohub.IOLoop.instance()
            self.setup_command_reciever()
            self.state_pub = zerohub.AsyncSender(self.mq_cfg.state, name = 'player')

            # Drop any privs to get ready for full operation.  Do this
            # before opening the sink, since we generally need to be
            # able to reopen it with the reduced privs anyway
            if self.uid and self.gid:
                if os.geteuid() == 0:
                    try:
                        self.log('dropping privs to uid {0} gid {1}',
                                 self.uid, self.gid)

                        os.setgid(self.gid)
                        os.setuid(self.uid)
                    except OSError, e:
                        raise PlayerError("can't set UID or GID: {0}".format(e))
                else:
                    self.log('not root, not changing uid or gid')
                    
            self.transport = Transport(
                self,
                sink.SINKS[self.cfg.audio_device_type](self))

            self.log('sending state to {}', self.mq_cfg.state)
            self.log('receiving commands on {}', self.mq_cfg.player_commands)
            self.log('receiving RPC on {}', self.mq_cfg.player_rpc)


            # Force out a bunch of updates at the start to improve the
            # chance that already running state subscribers get the
            # update
            for i in range(30):
                self.io_loop.add_timeout(time.time() + i, self.force_state_update)

            # Kick off IO loop to drive the rest of the events
            self.io_loop.start()

        finally:
            if self.transport:
                self.transport.shutdown()
        

    #
    # Command processing
    #

    def setup_command_reciever(self):
        # Discover command handlers dynamically
        callbacks = {}
        for name in dir(self):
            if name.startswith('cmd_'):
               func = getattr(self, name)
               if callable(func):
                   callbacks[name[4:]] = (
                       lambda reciever, msg, func2 = func:
                       self.handle_command(msg, func2))

        self.command_reciever = zerohub.Receiver(
            self.mq_cfg.player_commands,
            name = 'player',
            io_loop = self.io_loop,
            callbacks = callbacks,
            fallback = self.handle_unknown_command)

        self.rpc_reciever = zerohub.Receiver(
            self.mq_cfg.player_rpc,
            name = 'player',
            io_loop = self.io_loop,
            callbacks = callbacks,
            fallback = self.handle_unknown_command)


    def handle_command(self, cmd_args, cmd_func):
        try:
            self.debug('got command: {0}', cmd_args)

            cmd = cmd_args[0]
            args = cmd_args[1:]

            result = cmd_func(args)

            if isinstance(result, State):
                result_type = 'state'
            elif isinstance(result, RipState):
                result_type = 'rip_state'
            elif isinstance(result, model.ExtDisc) or cmd == 'source':
                result_type = 'disc'
            else:
                result_type = 'ok'

            return (result_type, serialize.get_jsons(result))

        except CommandError as e:
            self.log('command failed: {0}', e)
            return ('error', str(e))

        except:
            self.log('exception in command: {0}', cmd_args)
            traceback.print_exc(file = self.log_file)
            return ('error', 'unexpected error: {0}'.format(
                traceback.format_exc()))


    def handle_unknown_command(self, receiver, msg_parts):
        self.log('got unknown command on {0}: {1}', receiver, msg_parts)
        return ('error', 'unknown command: {0}'.format(msg_parts))


    def cmd_disc(self, args):
        source_disc_id = None

        if args:
            # Play disc in database by its ID
            did = args[0]

            disc = None
            if db.Database.is_valid_disc_id(did):
                disc = self.db.get_disc_by_disc_id(did)
            elif db.Database.is_valid_db_id(did):
                disc = self.db.get_disc_by_db_id(did)

            if disc is None:
                raise CommandError('invalid disc or database ID: {0}'.format(did))
        else:
            # Play inserted physical disc
            if self.ripper:
                raise CommandError("already ripping disc, can't rip another one yet")

            try:
                ripper = rip.Ripper(self)
                disc = ripper.read_disc()

                # Do first tick immediately to trigger any RipErrors here
                if ripper.tick():
                    # Ok, keep track of it and tick it
                    self.ripper = ripper
                    self.io_loop.add_timeout(time.time() + 1, self.tick_ripper)

            except rip.RipError, e:
                raise CommandError('rip failed: {}'.format(e))

            # Only follow links for physical discs.  When the user
            # starts a disc by ID we assume they really want to listen
            # to that one.
            disc, source_disc_id = self.resolve_alias_links(disc)

        # Stash the source disc into the resolved one.  Slightly ugly
        # messing with model.DbDisc like this, but it's simple.
        disc.source_disc_id = source_disc_id
        return self.play_disc(disc)


    def cmd_stop(self, args):
        return self.transport.stop()


    def cmd_play(self, args):
        return self.transport.play()


    def cmd_pause(self, args):
        return self.transport.pause()


    def cmd_play_pause(self, args):
        return self.transport.play_pause()


    def cmd_next(self, args):
        return self.transport.next()
        

    def cmd_prev(self, args):
        return self.transport.prev()


    def cmd_quit(self, args):
        self.log('quitting on command')
        if self.ripper:
            self.log('but letting currently running ripping process finish first')

        # Stop after a delay
        self.io_loop.add_timeout(time.time() + 0.5, self.eventually_stop)

        return self.transport.shutdown()


    def cmd_eject(self, args):
        if self.ripper:
            self.ripper.stop()
            self.ripper = None

        state = self.transport.eject()

        # Eject the disc with the help of an external command. There's
        # far too many ioctls to keep track of to do it ourselves.
        if self.cfg.eject_command:
            args = [self.cfg.eject_command, self.cfg.cdrom_device]
            try:
                subprocess.check_call(
                    args,
                    close_fds = True,
                    stdout = self.log_file,
                    stderr = subprocess.STDOUT)
            except OSError, e:
                self.log("error executing command {0!r}: {1}:", args, e)
            except subprocess.CalledProcessError, e:
                self.log("{0}", e)

        return state


    def cmd_state(self, args):
        return self.transport.get_state()


    def cmd_rip_state(self, args):
        # Since the ripper is ticked by this thread,
        # we can just respond with the state as-is
        if self.ripper:
            return self.ripper.state
        else:
            # Dummy inactive state
            return RipState()


    def cmd_source(self, args):
        return self.transport.get_source_disc()


    def cmd_version(self, args):
        return full_version()


    #
    # Internal methods
    #

    def eventually_stop(self):
        """Called when shutdown has been requested after a
        timeout to allow any IO to wrap up.

        Will reschedule itself until any running ripping
        process is finished.
        """

        if self.ripper:
            self.io_loop.add_timeout(time.time() + 3, self.eventually_stop)
        else:
            self.io_loop.stop()


    def tick_ripper(self):
        """Run once a second as long as there is a ripper.
        Sets up the next call to itself if relevant.
        """
        try:
            if self.ripper.tick():
                # Ok, keep going
                self.io_loop.add_timeout(time.time() + 1, self.tick_ripper)
            else:
                # Done
                self.ripper = None

        except rip.RipError, e:
            self.debug('dropping failed ripper')
            self.ripper = None

        if not self.ripper:
            self.transport.ripping_done()


    def resolve_alias_links(self, disc):
        """Follow any disc alias links, returning the disc that should really
        be played.

        Any errors are handled by just returning whatever disc has
        been reached in the chain, as that is probably good enough to
        play.
        """

        # Keep track of the disc that started the link
        source_disc = disc
        source_disc_id = None

        # Avoid getting stuck in circles
        visited = set()
        visited.add(disc.disc_id)

        while disc.link_type == 'alias':
            if disc.linked_disc_id:
                linked = self.db.get_disc_by_disc_id(disc.linked_disc_id)
            else:
                linked = None

            if not linked:
                self.log('error: missing alias link from {} to {}',
                         disc, disc.linked_disc_id)
                break

            if linked.disc_id in visited:
                self.log('error: alias link circle from {} to {}',
                         disc, linked)
                break

            self.debug('following alias link from {} to {}',
                       disc, linked)

            visited.add(linked.disc_id)
            disc = linked
            source_disc_id = source_disc.disc_id

        return disc, source_disc_id


    def play_disc(self, disc, track_number = 0):
        """Start playing disc from the database"""

        self.log('playing disc: {0}', disc)

        # Filter out skipped tracks
        disc.tracks = [t for t in disc.tracks if not t.skip]

        is_ripping = self.ripper is not None
        src = source.PCMDiscSource(self, disc, is_ripping)
        return self.transport.new_source(src, track_number)


    #
    # State publishing
    #

    def publish_state(self, state):
        self.state_pub.send_multipart(['state', serialize.get_jsons(state)])

    def publish_rip_state(self, rip_state):
        self.state_pub.send_multipart(['rip_state', serialize.get_jsons(rip_state)])

    def publish_disc(self, disc):
        self.state_pub.send_multipart(['disc', serialize.get_jsons(disc)])

    def force_state_update(self):
        self.publish_state(self.transport.get_state())

        if self.ripper:
            self.publish_rip_state(self.ripper.state)
        else:
            # Send a dummy state
            self.publish_rip_state(RipState())

    #
    # Utility
    #

    def log(self, msg, *args, **kwargs):
        m = (time.strftime('%Y-%m-%d %H:%M:%S ') + threading.current_thread().name + ': '
             + msg.format(*args, **kwargs) + '\n')
        self.log_file.write(m)
        self.log_file.flush()

        
    def debug(self, msg, *args, **kwargs):
        if self.log_debug:
            self.log(msg, *args, **kwargs)


class Transport(object):
    """
    The Transport moves samples from a Source to a Sink, i.e. in this
    context primarily from a disc to an audio device.  All the while
    it is responsible for updating the state of the player, as well as
    implementing the commands from the Player.

    There are two threads managed by this class.  The source thread
    gets audio packets from a Source iterator and pushes them onto a
    Queue, which is then read by the sink thread which sends them to
    the audio sink and updates the state according to the current
    played position.

    To coordinate everything, the transport runs in contexts,
    identified by a simple increasing integer.  Each command that that
    may require that the source is changed or repositioned bumps up
    the context count, so the threads can determine that they must now
    reset stuff.

    On such disruptive changes, the state is updated immediately by
    the method that bumps up the context.  During normal play,
    including stopping at the end of the disc, the sink thread is
    responsible for updating the state.

    The unit tests in test/test_player.py serve as pretty good
    documentation on how this class works.
    """

    # Perhaps make this configurable sometime
    MAX_BUFFER_SECS = 20
    PACKETS_PER_SECOND = 5


    # Minimal packet-ish thing to signal end of stream from source
    # thread to sink thread
    class END_OF_STREAM:
        def __init__(self, context):
            self.context = context


    def __init__(self, player, sink):
        self.player = player
        self.log = player.log
        self.debug = player.debug

        self.sink = sink

        self.queue = Queue.Queue(self.PACKETS_PER_SECOND * self.MAX_BUFFER_SECS)

        # The following members can only be accessed when holding the lock
        self.lock = threading.Lock()
        self.context = 0
        self.source = None
        self.start_track = 0
        self.state = State()
        self.paused_by_user = False

        # Event objects to tell the source and sink threads that the
        # context has changed to allow them to react faster
        self.source_context_changed = threading.Event()
        self.sink_context_changed = threading.Event()

        # End of self.lock protected members

        # Write NO_DISC state at startup
        self.update_disc()
        self.update_state()

        # Kick off the threads
        source_thread = threading.Thread(target = self.source_thread,
                                         name = 'transport source')
        sink_thread = threading.Thread(target = self.sink_thread,
                                       name = 'transport sink')
        
        source_thread.daemon = True
        sink_thread.daemon = True

        source_thread.start()
        sink_thread.start()


    def get_state(self):
        with self.lock:
            return copy.copy(self.state)


    def get_source_disc(self):
        with self.lock:
            if self.source:
                return model.ExtDisc(self.source.disc)
            else:
                return None


    #
    # Commands changing transport state
    # 

    def shutdown(self):
        with self.lock:
            if self.state.state == State.OFF:
                return

            self.log('transport shutting down')
            self.sink.stop()

            self.new_context()
            self.source = None
            self.start_track = None
            self.update_disc()

            self.state = State()
            self.state.state = State.OFF
            self.update_state()

            return copy.copy(self.state)


    def new_source(self, source, track = 0):
        with self.lock:
            if self.state.state == State.WORKING:
                raise CommandError('ignoring new_source while WORKING')

            self.debug('new source for disc: {0} state: {1}'.format(
                    source.disc.disc_id, self.state.state.__name__))

            if self.state.state in (State.PLAY, State.PAUSE):
                self.sink.stop()

            self.source = source
            self.update_disc()

            self.start_new_track(track)

            return copy.copy(self.state)


    def eject(self):
        with self.lock:
            if self.state.state == State.NO_DISC:
                return
            
            self.log('transport ejecting source')
            self.sink.stop()

            self.new_context()
            self.source = None
            self.start_track = None
            self.update_disc()

            self.set_state_no_disc()

            return copy.copy(self.state)

            
    def play(self):
        with self.lock:
            if self.state.state == State.STOP:
                self.log('transport playing from STOP')
                self.start_new_track(0)

            elif self.state.state == State.PAUSE:
                self.do_resume()

            else:
                raise CommandError('ignoring play() in state {0}'.format(
                    self.state.state))

            return copy.copy(self.state)


    def pause(self):
        with self.lock:
            if self.state.state == State.PLAY:
                self.do_pause()
            else:
                raise CommandError('ignoring pause() in state {0}'.format(
                    self.state.state))

            return copy.copy(self.state)

    def play_pause(self):
        with self.lock:
            if self.state.state == State.STOP:
                self.log('transport playing from STOP')
                self.start_new_track(0)

            elif self.state.state == State.PLAY:
                self.do_pause()

            elif self.state.state == State.PAUSE:
                self.do_resume()

            else:
                raise CommandError('ignoring play() in state {0}'.format(
                    self.state.state))

            return copy.copy(self.state)


    def stop(self):
        with self.lock:
            if self.state.state not in (State.PLAY, State.PAUSE):
                raise CommandError('ignoring stop() in state {0}'.format(
                    self.state.state))

            self.log('transport stopping')
            self.sink.stop()

            self.new_context()
            self.start_track = None
            self.set_state_stop()
            return copy.copy(self.state)


    def prev(self):
        with self.lock:
            if self.state.state == State.STOP:
                self.log('transport playing from STOP on command prev')
                self.start_new_track(self.state.no_tracks - 1)

            elif self.state.state in (State.PLAY, State.PAUSE):
                self.sink.stop()

                # Calcualte which track is next (first track in state is 1)
                assert self.state.track >= 1

                # If the track position is within the first two seconds or
                # the pregap, skip to the previous track.  Otherwise replay
                # this track from the start

                if self.state.position < 2:
                    self.log('transport skipping to previous track')
                    tn = self.state.track - 1
                else:
                    self.log('transport restarting current track')
                    tn = self.state.track

                if tn > 0:
                    self.start_new_track(tn - 1)
                else:
                    self.log('transport stopping on skipping past first track')
                    self.new_context()
                    self.start_track = None
                    self.set_state_stop()
            else:
                raise CommandError('ignoring prev() in state {0}'.format(
                    self.state.state))

            return copy.copy(self.state)


    def next(self):
        with self.lock:
            if self.state.state == State.STOP:
                self.log('transport playing from STOP on command next')
                self.start_new_track(0)

            elif self.state.state in (State.PLAY, State.PAUSE):
                self.sink.stop()

                # Since state.track is 1-based, comparison and next
                # track here don't need to add 1
                if self.state.track < self.state.no_tracks:
                    self.log('transport skipping to next track')
                    self.start_new_track(self.state.track)
                else:
                    self.log('transport stopping on skipping past last track')
                    self.new_context()
                    self.start_track = None
                    self.set_state_stop()
            else:
                raise CommandError('ignoring next() in state {0}'.format(
                    self.state.state))

            return copy.copy(self.state)


    def ripping_done(self):
        with self.lock:
            # Special case: if the rip process failed, we
            # didn't get any packets from the streamer and
            # never got out of the working state.  Handle that
            # here by telling that process to stop and
            # manually go back to NO_DISC.

            if self.state.state == State.WORKING:
                self.log('ripping seems to have failed, since state is still WORKING')

                self.new_context()
                self.source = None
                self.start_track = None
                self.set_state_no_disc()


    #
    # State updating methods.  self.lock must be held when calling these
    #

    def do_pause(self):
        self.log('transport pausing')

        # this is not a new context, the sink just pauses packet playback
        if self.sink.pause():
            self.state.state = State.PAUSE
            self.update_state()
            self.paused_by_user = True
        else:
            self.log('sink refused to pause, keeping PLAY')


    def do_resume(self):
        if self.paused_by_user:
            self.log('resuming paused transport')

            # This is not a new context, we want to keep
            # playing buffered packets
            self.sink.resume()
            self.state.state = State.PLAY
            self.update_state()

        else:
            self.log('paused after track, playing')

            # New context - we've lost everything in
            # the buffer anyway (see sink_stopped())
            self.start_new_track(self.state.track)


    def start_new_track(self, track):
        self.new_context()
        self.start_track = track
        self.set_state_working()

    def new_context(self):
        self.context += 1
        self.source_context_changed.set()
        self.sink_context_changed.set()
        self.log('setting new context: {0}'.format(self.context))

    def set_state_no_disc(self):
        self.state = State()
        self.update_state()
        

    def set_state_working(self):
        self.state.state = State.WORKING
        self.state.disc_id = self.source.disc.disc_id
        self.state.source_disc_id = self.source.disc.source_disc_id
        self.state.track = self.start_track + 1
        self.state.no_tracks = len(self.source.disc.tracks)
        self.state.index = 0
        self.state.position = 0
        self.state.length = 0
        self.update_state()

                
    def set_state_stop(self):
        self.state.state = State.STOP
        self.state.track = 0
        self.state.index = 0
        self.state.position = 0
        self.state.length = 0
        self.update_state()
    

    def update_state(self, log_state = True):
        if log_state:
            self.debug('state: {0}', self.state)

        self.player.publish_state(self.state)


    def update_disc(self):
        disc = model.ExtDisc(self.source.disc) if self.source else None
        self.player.publish_disc(disc)

    #
    # Source thread
    #

    def source_thread(self):
        try:
            self.source_loop()
        except:
            traceback.print_exc()
            sys.exit(1)


    def source_loop(self):
        while True:
            # Wait until there's something to play
            self.source_context_changed.wait()
            with self.lock:
                context = self.context
                src = self.source
                start_track = self.start_track

                # start_track behaves like a command to us on context
                # changes, so reset it to avoid stale information
                # influencing future contexts
                self.start_track = None

                self.source_context_changed.clear()
                self.log('using new context: {0}'.format(context))

            if src and start_track is not None:
                self.debug('starting source: {0} at track {1}'.format(src.disc, start_track))

                # Packet loop: get packets from the source until we're told
                # to do something else or reaches the end

                try:
                    for packet in src.iter_packets(start_track, self.PACKETS_PER_SECOND):
                        if self.source_context_changed.is_set():
                            break

                        if packet is not None:
                            packet.context = context
                            self.queue.put(packet)

                    else:
                        self.debug('reached end of disc')
                        self.queue.put(self.END_OF_STREAM(context))

                except source.SourceError, e:
                    self.log('source error for disc {0}: {1}'.format(src.disc, e))


    #
    # Sink thread
    #

    def sink_thread(self):
        try:
            self.sink_loop()
        except:
            traceback.print_exc()
            sys.exit(1)

    def sink_loop(self):
        class IDLE: pass
        class ADDING_PACKETS: pass
        class DRAINING: pass
        state = IDLE

        context = 0

        while True:
            packet = self.queue.get()

            with self.lock:
                # If something's changed while not idle, go back to
                # IDLE state to wait for first packet of new stream
                if context != self.context:
                    if state != IDLE:
                        state = IDLE
                    context = self.context
                    self.sink_context_changed.clear()
                    self.log('using new context: {0}'.format(context))

            # Discard packets for an older context
            if packet.context != context:
                packet = None

            pause_when_drained = False

            if isinstance(packet, self.END_OF_STREAM):
                if state == ADDING_PACKETS:
                    state = DRAINING
                else:
                    self.sink_stopped(packet.context)
                packet = None

            if packet:
                if state == IDLE:
                    if self.sink_start_playing(packet):
                        state = ADDING_PACKETS

                if state == ADDING_PACKETS:
                    self.sink_packet(packet)

                    if packet.flags & packet.PAUSE_AFTER:
                        state = DRAINING
                        pause_when_drained = True

            if state == DRAINING:
                self.sink_drain(context, pause_when_drained)
                state = IDLE


    def sink_start_playing(self, packet):
        with self.lock:
            if packet.context == self.context:
                self.debug('starting to play disc: {0}'.format(packet.disc.disc_id))

                self.sink.start(packet.format)
                self.state.state = State.PLAY
                self.state.disc_id = packet.disc.disc_id
                self.state.no_tracks = len(packet.disc.tracks)
                self.state.track = packet.track_number + 1
                self.state.index = packet.index
                self.state.position = int(packet.rel_pos / packet.format.rate)
                self.state.length = int((packet.track.length - packet.track.pregap_offset)
                                        / packet.format.rate)
                self.update_state()

                return True
            else:
                return False


    def sink_stopped(self, context, paused_after_track = False):
        with self.lock:
            if context == self.context:
                # if context had changed, then stop would already have
                # been called
                self.sink.stop()

                if paused_after_track:
                    self.state.state = State.PAUSE
                    self.update_state()
                    self.paused_by_user = False

                    # Usually this is signalled from the main thread,
                    # but here we are applying a command on behalf of
                    # the user.  That needs a new context to get the
                    # sink thread to stop playing buffered packets and
                    # the source thread to stop generating them.
                    self.new_context()
                else:
                    self.set_state_stop()


    def sink_packet(self, packet):
        offset = 0
        while offset < len(packet.data):
            if self.sink_context_changed.is_set():
                return
            
            sunk, playing_packet, error = self.sink.add_packet(packet, offset)
            offset += sunk
            if playing_packet or error:
                self.sink_update_state(playing_packet, error)


    def sink_drain(self, context, pause_when_drained):
        while True:
            if self.sink_context_changed.is_set():
                return

            res = self.sink.drain()
            if res is None:
                self.sink_stopped(context, pause_when_drained)
                return
            else:
                playing_packet, error = res                
                if playing_packet or error:
                    self.sink_update_state(playing_packet, error)


    def sink_update_state(self, packet, error):
        if error:
            error = 'Audio sink error: {0}'.format(error)

        with self.lock:
            # Always update the device error, regardless of context
            if error != self.state.error:
                self.state.error = error
                self.update_state()

            if not packet:
                return

            # If the context of this packet is no longer valid, just ignore it
            if packet.context != self.context:
                return
            
            pos = int(packet.rel_pos / packet.format.rate)

            if self.state.disc_id != packet.disc.disc_id:
                self.state.disc_id = packet.disc.disc_id
                self.state.no_tracks = len(packet.disc.tracks)
                self.state.track = packet.track_number + 1
                self.state.index = packet.index
                self.state.position = pos
                self.state.length = int((packet.track.length - packet.track.pregap_offset)
                                        / packet.format.rate)
                self.update_state()

            elif (self.state.track != packet.track_number + 1
                or self.state.index != packet.index):
                self.state.track = packet.track_number + 1
                self.state.index = packet.index
                self.state.position = pos
                self.state.length = int((packet.track.length - packet.track.pregap_offset)
                                        / packet.format.rate)
                self.update_state()

            # Moved backward in track
            elif pos < self.state.position:
                self.state.position = pos
                self.update_state()

            # Moved a second (not worth logging)
            elif pos != self.state.position:
                self.state.position = pos
                self.update_state(False)

