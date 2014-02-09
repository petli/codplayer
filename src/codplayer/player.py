# codplayer - player state 
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes implementing the player core and it's state.

The unit of time in all objects is one audio frame.
"""

import sys
import os
import pwd
import grp
import errno
import select
import subprocess
import time
import threading
import Queue
import traceback

from musicbrainz2 import disc as mb2_disc

from . import db
from . import model
from . import serialize
from . import source
from . import sink

class PlayerError(Exception):
    pass

class State(serialize.Serializable):
    """Player state as visible to external users.  Attributes:

    state: One of the state identifiers:
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

    ripping: False if not currently ripping a disc, otherwise a number
    0-100 showing the percentage done.

    audio_device_error: A string giving the error state of the audio device, if any.
    """

    class NO_DISC:
        valid_commands = ('quit', 'disc', 'eject')

    class WORKING:
        valid_commands = ('quit', )

    class PLAY:
        valid_commands = ('quit', 'pause', 'play_pause',
                          'next', 'prev', 'stop', 'eject')

    class PAUSE:
        valid_commands = ('quit', 'play', 'play_pause',
                          'next', 'prev', 'stop', 'eject')

    class STOP:
        valid_commands = ('quit', 'play', 'play_pause',
                          'next', 'prev', 'eject')


    def __init__(self):
        self.state = self.NO_DISC
        self.disc_id = None
        self.track = 0
        self.no_tracks = 0
        self.index = 0
        self.position = 0
        self.length = 0
        self.ripping = False
        self.error = None


    def __str__(self):
        return ('{state.__name__} disc: {disc_id} track: {track}/{no_tracks} '
                'index: {index} position: {position} length: {length} ripping: {ripping} '
                'error: {error}'
                .format(**self.__dict__))


    # Deserialisation methods
    MAPPING = (
        serialize.Attr('state', enum = (NO_DISC, WORKING, PLAY, PAUSE, STOP)),
        serialize.Attr('disc_id', str),
        serialize.Attr('track', int),
        serialize.Attr('no_tracks', int),
        serialize.Attr('index', int),
        serialize.Attr('position', int),
        serialize.Attr('ripping', (bool, int)),
        serialize.Attr('error', serialize.str_unicode),
        )

    @classmethod
    def from_file(cls, path):
        """Create a State object from the JSON stored in the file PATH."""
        return serialize.load_json(cls, path)
        

class Player(object):

    def __init__(self, cfg, database, log_file, control_fd):
        self.cfg = cfg
        self.db = database
        self.log_file = log_file
        self.log_debug = True

        self.transport = None
        
        self.rip_process = None
        self.playing_physical_disc = False

        self.ripping_audio_path = None
        self.ripping_audio_size = None
        self.ripping_source = None

        self.keep_running = True

        self.control = CommandReader(control_fd)
        self.poll = select.poll()
        self.poll.register(self.control, select.POLLIN)

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
        try:
            self.transport = Transport(
                self, sink.SINKS[self.cfg.audio_device_type](self))

            # Now that device is running, drop any privs to get ready
            # for full operation
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
                    
            # Main loop, executing until a quit command is received.
            # However, don't stop if a rip process is currently running.

            while self.keep_running or self.rip_process is not None:
                self.run_once(1000)

        finally:
            # Eject any disc to reset state to leave less mess behind
            if self.transport:
                self.transport.eject()
        

    #
    # Internal methods
    # 

    def run_once(self, ms_timeout):
        fds = self.poll.poll(ms_timeout)

        # Process input
        for fd, event in fds:
            if fd == self.control.fileno():
                for cmd_args in self.control.handle_data():
                    self.handle_command(cmd_args)

        # Check if any current ripping process is finished
        if self.rip_process is not None:
            rc = self.rip_process.poll()
            if rc is None:
                # Still in progress, just check how far into the disc it is
                assert self.ripping_audio_size > 0
                try:
                    stat = os.stat(self.ripping_audio_path)
                    done = int(100 * (float(stat.st_size) / self.ripping_audio_size))
                except OSError:
                    done = 0

                self.transport.set_ripping_progress(done)
            else:
                self.debug('ripping process finished with status {0}', rc)
                self.rip_process = None
                self.ripping_audio_path = None
                self.ripping_audio_size = None
                self.ripping_source = None

                self.transport.set_ripping_progress(None)

                    
    #
    # Command processing
    #
        
    def handle_command(self, cmd_args):
        self.debug('got command: {0}', cmd_args)

        cmd = cmd_args[0]
        args = cmd_args[1:]

        try:
            cmd_func = getattr(self, 'cmd_' + cmd)
        except AttributeError:
            self.log('invalid command: {1}', cmd)
            return

        cmd_func(args)
        

    def cmd_disc(self, args):
        if self.rip_process:
            self.log("already ripping disc, can't rip another one yet")
            return

        self.playing_physical_disc = False

        if args:
            # Play disc in database by its ID
            did = args[0]

            disc = None
            if db.Database.is_valid_disc_id(did):
                disc = self.db.get_disc_by_disc_id(did)
            elif db.Database.is_valid_db_id(did):
                disc = self.db.get_disc_by_db_id(did)

            if disc is None:
                self.log('invalid disc or database ID: {0}', did)
                return

            self.play_disc(disc)
        else:
            # Play inserted physical disc
            self.debug('disc inserted, reading ID')

            # Use Musicbrainz code to get the disc signature
            try:
                mbd = mb2_disc.readDisc(self.cfg.cdrom_device)
            except mb2_disc.DiscError, e:
                self.log('error reading disc in {0}: {1}',
                         self.cfg.cdrom_device, e)
                return

            # Is this already ripped?
            disc = self.db.get_disc_by_disc_id(mbd.getId())

            if disc is None:
                # No, rip it and get a Disc object good enough for playing 
                self.playing_physical_disc = True
                disc = self.rip_disc(mbd)
                if not disc:
                    return

            self.play_disc(disc)


    def cmd_stop(self, args):
        self.transport.stop()


    def cmd_play(self, args):
        self.transport.play()


    def cmd_pause(self, args):
        self.transport.pause()


    def cmd_play_pause(self, args):
        self.transport.play_pause()


    def cmd_next(self, args):
        self.transport.next()
        

    def cmd_prev(self, args):
        self.transport.prev()
        return

        if self.state.state == State.STOP:
            # Start playing the last track
            assert self.current_disc is not None
            self.play_disc(self.current_disc, len(self.current_disc.tracks) - 1)
            return

        # Calcualte which track is next (first track is 1)
        assert self.state.track >= 1
            
        # If the track position is within the first two seconds or
        # the pregap, skip to the previous track.  Otherwise replay
        # this track from the start

        if self.state.position < 2:
            tn = self.state.track - 1
        else:
            tn = self.state.track

        # Stop any current streamer, setting skipped flag if this will
        # not stop playback.
        if self.streamer:
            self.streamer.shutdown(tn != 0)
            self.streamer = None

        # If the player is paused, it must be resumed.  This will
        # result in the glitch that whatever is queued up in the
        # hardware buffer will be played, followed by the previous
        # track (see cmd_stop() above).

        if self.state.state == State.PAUSE:
            self.device.resume()
            self.state.state = State.PLAY
            self.write_state()

        if self.state.state == State.PLAY:

            # If this reaches the start of the disc, just stop.
            # Nothing has to be done for that, as update_state()
            # below will react to the stop of the stream.
            if tn == 0:
                return

            # Start playing the selected track (now counting from 0,
            # not 1...)
            self.streamer = AudioStreamer(self, self.current_disc, tn - 1,
                                          self.rip_process is not None)
            self.device.play_stream(self.streamer.iter_packets())

            # Don't update state here, wait for the packet update
            # to do it

        else:
            raise PlayerError('unexpected state for cmd_prev: {0}', self.state)


    def cmd_quit(self, args):
        self.log('quitting on command')
        if self.rip_process is not None:
            self.log('but letting currently running cdrdao process finish first')
            
        self.keep_running = False
        self.transport.stop()


    def cmd_eject(self, args):
        self.transport.eject()

        # Eject the disc with the help of an external command. There's
        # far too many ioctls to keep track of to do it ourselves.
        if self.playing_physical_disc and self.cfg.eject_command:
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


    def rip_disc(self, mbd):
        """Set up the process of ripping a disc that's not in the
        database, based on the Musicbrainz Disc object
        """
        
        # Turn Musicbrainz disc into our Disc object
        db_id = self.db.disc_to_db_id(mbd.getId())
        path = self.db.create_disc_dir(db_id)

        disc = model.DbDisc.from_musicbrainz_disc(
            mbd, filename = self.db.get_audio_path(db_id))
        
        self.log('ripping new disk: {0}', disc)

        # Build the command line
        args = [self.cfg.cdrdao_command,
                'read-cd',
                '--device', self.cfg.cdrom_device,
                '--datafile', self.db.get_audio_file(db_id),
                self.db.get_orig_toc_file(db_id),
                ]

        try:
            log_path = os.path.join(path, 'cdrdao.log')
            log_file = open(log_path, 'wt')
        except IOError, e:
            self.log("error ripping disc: can't open log file {0}: {1}",
                     log_path, e)
            return False

        self.debug('executing command in {0}: {1!r}', path, args)
                
        try:
            self.rip_process = subprocess.Popen(
                args,
                cwd = path,
                close_fds = True,
                stdout = log_file,
                stderr = subprocess.STDOUT)
        except OSError, e:
            self.log("error executing command {0!r}: {1}:", args, e)
            return None

        return disc


    def play_disc(self, disc, track_number = 0):
        """Start playing disc from the database"""

        self.log('playing disc: {0}', disc)


        if self.rip_process is not None:
            src = source.PCMDiscSource(self, disc, True)

            db_id = self.db.disc_to_db_id(disc.disc_id)
            self.ripping_audio_path = self.db.get_audio_path(db_id)
            self.ripping_audio_size = disc.get_disc_file_size_bytes()
            self.ripping_source = src
            self.transport.set_ripping_progress(0)
        else:
            src = source.PCMDiscSource(self, disc, False)
        
        self.transport.new_source(src, track_number)


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
        self.log = player.log
        self.debug = player.debug
        self.cfg = player.cfg

        self.sink = sink

        self.queue = Queue.Queue(self.PACKETS_PER_SECOND * self.MAX_BUFFER_SECS)

        # The following members can only be accessed when holding the lock
        self.lock = threading.Lock()
        self.context = 0
        self.source = None
        self.start_track = 0
        self.state = State()

        # Event objects to tell the source and sink threads that the
        # context has changed to allow them to react faster
        self.source_context_changed = threading.Event()
        self.sink_context_changed = threading.Event()

        # End of self.lock protected members

        # Write NO_DISC state at startup
        self.write_state()
        self.write_disc()

        # Kick off the threads
        source_thread = threading.Thread(target = self.source_thread,
                                         name = 'transport source')
        sink_thread = threading.Thread(target = self.sink_thread,
                                       name = 'transport sink')
        
        source_thread.daemon = True
        sink_thread.daemon = True

        source_thread.start()
        sink_thread.start()


    #
    # Commands changing transport state
    # 

    def new_source(self, source, track = 0):
        with self.lock:
            self.debug('new source for disc: {0} state: {1}'.format(
                    source.disc.disc_id, self.state.state.__name__))

            if self.state.state in (State.PLAY, State.PAUSE):
                self.sink.stop()

            self.context += 1
            self.source_context_changed.set()
            self.sink_context_changed.set()

            self.source = source
            self.start_track = track
            self.set_state_working()
            
            self.write_disc()


    def eject(self):
        with self.lock:
            if self.state.state == State.NO_DISC:
                return
            
            self.log('transport ejecting source')
            self.sink.stop()
            self.context += 1
            self.source_context_changed.set()
            self.sink_context_changed.set()

            self.source = None
            self.start_track = None
            self.set_state_no_disc()

            self.write_disc()

            
    def play(self):
        with self.lock:
            if self.state.state == State.STOP:
                self.log('transport playing from STOP')
                self.context += 1
                self.start_track = 0
                self.source_context_changed.set()
                self.sink_context_changed.set()
                self.set_state_working()


    def pause(self):
        pass
    
    def play_pause(self):
        pass

    
    def stop(self):
        with self.lock:
            if self.state.state == State.STOP:
                return
            
            self.log('transport stopping')
            self.sink.stop()
            self.context += 1
            self.source_context_changed.set()
            self.sink_context_changed.set()

            self.start_track = None
            self.set_state_stop()


    def prev(self):
        pass

    def next(self):
        pass

    def set_ripping_progress(self, done):
        with self.lock:
            if done == self.state.ripping:
                return
            
            if done is None:
                self.state.ripping = None
                self.write_state()
                
                # Special case: if the rip process failed, we
                # didn't get any packets from the streamer and
                # never got out of the working state.  Handle that
                # here by telling that process to stop and
                # manually go back to NO_DISC.

                if self.state.state == State.WORKING:
                    self.context += 1
                    self.source_context_changed.set()
                    self.sink_context_changed.set()

                    self.source = None
                    self.start_track = None
                    self.set_state_no_disc()

            else:
                # Update progress, but no point logging it
                self.state.ripping = done
                self.write_state(False)

                
    #
    # State updating methods.  self.lock must be held when calling these
    #

    def set_state_no_disc(self):
        self.state = State()
        self.write_state()
        

    def set_state_working(self):
        self.state.state = State.WORKING
        self.state.disc_id = self.source.disc.disc_id
        self.state.track = 0
        self.state.no_tracks = len(self.source.disc.tracks)
        self.state.index = 0
        self.state.position = 0
        self.state.length = 0
        self.write_state()

                
    def set_state_stop(self):
        self.state.state = State.STOP
        self.state.track = 0
        self.state.index = 0
        self.state.position = 0
        self.state.length = 0
        self.write_state()
    

    def write_state(self, log_state = True):
        if log_state:
            self.debug('state: {0}', self.state)

        # TODO: should this be done by a helper thread instead?
        serialize.save_json(self.state, self.cfg.state_file)


    def write_disc(self):
        if self.source:
            serialize.save_json(model.ExtDisc(self.source.disc), self.cfg.disc_file)
        else:
            serialize.save_json(None, self.cfg.disc_file)

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
                self.source_context_changed.clear()

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

            # Discard packets for an older context
            if packet.context != context:
                packet = None

            if isinstance(packet, self.END_OF_STREAM):
                if state == ADDING_PACKETS:
                    state = DRAINING
                else:
                    self.sink_stopped(packet.context)
                packet = None

            if packet:
                if state == IDLE:
                    self.sink_start_playing(packet)
                    state = ADDING_PACKETS

                assert state == ADDING_PACKETS
                self.sink_packet(packet)

            if state == DRAINING:
                self.sink_drain(context)
                state = IDLE


    def sink_start_playing(self, packet):
        self.debug('starting to play disc: {0}'.format(packet.disc.disc_id))
        
        with self.lock:
            self.sink.start(packet.format)
            if packet.context == self.context:
                self.state.state = State.PLAY
                self.state.disc_id = packet.disc.disc_id
                self.state.no_tracks = len(packet.disc.tracks)
                self.state.track = packet.track_number + 1
                self.state.index = packet.index
                self.state.position = int(packet.rel_pos / packet.format.rate)
                self.state.length = int((packet.track.length - packet.track.pregap_offset)
                                        / packet.format.rate)
                self.write_state()


    def sink_stopped(self, context):
        with self.lock:
            if context == self.context:
                # if context had changed, then stop would already have
                # been called
                self.sink.stop()
                self.set_state_stop()


    def sink_packet(self, packet):
        offset = 0
        while offset < len(packet.data):
            if self.sink_context_changed.is_set():
                return
            
            sunk, playing_packet, error = self.sink.add_packet(packet, offset)
            offset += sunk
            if playing_packet:
                self.sink_update_state(playing_packet)


    def sink_drain(self, context):
        while True:
            if self.sink_context_changed.is_set():
                return

            res = self.sink.drain()
            if res is None:
                self.sink_stopped(context)
                return
            else:
                playing_packet, error = res                
                if playing_packet:
                    self.sink_update_state(playing_packet)


    def sink_update_state(self, packet):
        with self.lock:
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
                self.write_state()

            elif (self.state.track != packet.track.number
                or self.state.index != packet.index):
                self.state.track = packet.track_number + 1
                self.state.index = packet.index
                self.state.position = pos
                self.state.length = int((packet.track.length - packet.track.pregap_offset)
                                        / packet.format.rate)
                self.write_state()

            # Moved backward in track
            elif pos < self.state.position:
                self.state.position = pos
                self.write_state()

            # Moved a second (not worth logging)
            elif pos != self.state.position:
                self.state.position = pos
                self.write_state(False)


class CommandReader(object):
    """Wrapper around the file object for the command channel.

    It collects whole lines of input and returns an argv style list
    when complete.
    """

    def __init__(self, fd):
        self.fd = fd
        self.buffer = ''

    def fileno(self):
        """For compatibility with poll()"""
        return self.fd

    def handle_data(self):
        """Call when poll() says there's data to read on the control file.

        Acts as an iterator, generating all received commands
        (typically only one, though).  The command is split into an
        argv style list.
        """
        
        self.buffer += self.read_data()

        # Not a complete line yet
        if '\n' not in self.buffer:
            return

        lines = self.buffer.splitlines(True)

        # The last one may be a partial line, indicated by not having
        # a newline at the end
        last_line = lines[-1]
        if last_line and last_line[-1] != '\n':
            self.buffer = last_line
            del lines[-1]
        else:
            self.buffer = ''
            
        # Process the complete lines
        for line in lines:
            if line:
                assert line[-1] == '\n'
                cmd_args = line.split()
                if cmd_args:
                    yield cmd_args

    def read_data(self):
        """This function mainly exists to support the test cases for
        the class, allowing them to override the system call.
        """
        
        d = os.read(self.fd, 500)
        if not d:
            raise PlayerError('unexpected close of control file')

        return d
        
