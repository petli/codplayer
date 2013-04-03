# codplayer - player state 
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes implementing the player core and it's state.

The unit of time in all objects is one sample.
"""

import os
import errno
import select
import subprocess
import time
import threading
import Queue

from musicbrainz2 import disc as mb2_disc

from . import db, model, audio


class PlayerError(Exception):
    pass

class State(object):
    """Player state as visible to external users.  Attributes:

    state: One of the state identifiers:
      NO_DISC: No disc is loaded in the player
      WORKING: Disc has been loaded, waiting for streaming to start
      PLAY:    Playing disc normally
      PAUSE:   Disc is currently paused
      STOP:    Playing finished, but disc is still loaded

    disc_id: The Musicbrainz disc ID of the currently loaded disc, or None

    track_number: Current track being played, counting from 1. 0 if
                  stopped or no disc is loaded.

    no_tracks: Number of tracks on the disc to be played. 0 if no disc is loaded.

    index: Track index currently played. 0 for pre_gap, 1+ for main sections.

    position: Current position in track in whole seconds, counting
    from index 1 in whole samples (so the pregap is negative).

    ripping: True if disc is being ripped while playing, False if
    played off previously ripped copy.
    """

    class NO_DISC:
        valid_commands = ('quit', 'disc')

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
        self.track_number = 0
        self.no_tracks = 0
        self.index = 0
        self.position = 0
        self.ripping = False


    @classmethod
    def from_string(cls, json):
        pass

    def to_string(self):
        pass
    
    def __str__(self):
        return ('{state.__name__} disc: {disc_id} track: {track_number}/{no_tracks} '
                'index: {index} position: {position} ripping: {ripping}'
                .format(**self.__dict__))


class Player(object):

    def __init__(self, cfg, database, log_file, control_fd, dev_class):
        self.cfg = cfg
        self.db = database
        self.log_file = log_file
        self.log_debug = True

        self.device = dev_class(self, cfg)
        
        self.rip_process = None

        self.streamer = None
        self.current_disc = None

        self.state = State()
        self.write_state()

        self.keep_running = True

        self.control = CommandReader(control_fd)
        self.poll = select.poll()
        self.poll.register(self.control, select.POLLIN)

        
    def run(self):
        # Main loop, executing until a quit command is received.
        # However, don't stop if a rip process is currently running.

        while self.keep_running or self.rip_process is not None:
            # TODO: add general exception handling here
            self.run_once(500)
            

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
            if rc is not None:
                self.debug('ripping process finished with status {0}', rc)
                self.rip_process = None

                self.state.ripping = False
                self.write_state()
                
                if self.streamer:
                    self.streamer.rip_finished()

                    # Special case: if the rip process failed, we
                    # didn't get any packets from the streamer and
                    # never got out of the working state.  Handle that
                    # here by telling that process to stop and
                    # manually go back to NO_DISC.

                    if self.state.state == State.WORKING:
                        self.streamer.shutdown()
                        self.state.state = State.NO_DISC
                        self.write_state()
            
        self.update_state()

                    
    #
    # Command processing
    #
        
    def handle_command(self, cmd_args):
        self.debug('got command: {0}', cmd_args)

        cmd = cmd_args[0]
        args = cmd_args[1:]

        if cmd in self.state.state.valid_commands:
            getattr(self, 'cmd_' + cmd)(args)
        else:
            self.log('invalid command in state {0}: {1}',
                     self.state, cmd)


    def cmd_disc(self, args):
        if self.rip_process:
            self.log("already ripping disc, can't rip another one yet")
            return

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
            disc = self.rip_disc(mbd)
            if not disc:
                return

        self.play_disc(disc)


    def cmd_stop(self, args):
        if self.streamer:
            self.streamer.shutdown()
            self.streamer = None

        # Must resume playing is paused, as device threads may be
        # hanging not notice that the stream stopped.  This may result
        # in a brief snipped of sound as data cached in the hardware
        # buffer is played.  If doing a proper ALSA device, we can
        # change this to drop the buffered data.
        if self.state.state == State.PAUSE:
            self.device.resume()
            self.state.state = State.PLAY


    def cmd_play(self, args):
        if self.state.state == State.STOP:
            # Just restart playing
            assert self.current_disc is not None
            self.play_disc(self.current_disc)

        elif self.state.state == State.PAUSE:
            self.log('resuming audio')
            self.device.resume()

            self.state.state = State.PLAY
            self.write_state()

        else:
            raise PlayerError('unexpected state for cmd_play: {0}', self.state)


    def cmd_pause(self, args):
        if self.state.state == State.PLAY:
            self.log('pausing audio')
            self.device.pause()

            self.state.state = State.PAUSE
            self.write_state()

        else:
            raise PlayerError('unexpected state for cmd_pause: {0}', self.state)


    def cmd_play_pause(self, args):
        if self.state.state == State.STOP:
            # Just restart playing
            assert self.current_disc is not None
            self.play_disc(self.current_disc)

        elif self.state.state == State.PAUSE:
            self.log('resuming audio')
            self.device.resume()

            self.state.state = State.PLAY
            self.write_state()

        elif self.state.state == State.PLAY:
            self.log('pausing audio')
            self.device.pause()

            self.state.state = State.PAUSE
            self.write_state()

        else:
            raise PlayerError('unexpected state for cmd_play_pause: {0}', self.state)


    def cmd_next(self, args):
        if self.state.state == State.STOP:
            # simply start playing from the first track
            assert self.current_disc is not None
            self.play_disc(self.current_disc)
            return

        # Stop any current streamer
        if self.streamer:
            self.streamer.shutdown(True)
            self.streamer = None

        # If the player is paused, it must be resumed.  This will
        # result in the glitch that whatever is queued up in the
        # hardware buffer will be played, followed by the next track
        # (see cmd_stop() above).

        if self.state.state == State.PAUSE:
            self.device.resume()
            self.state.state = State.PLAY
            self.write_state()

        if self.state.state == State.PLAY:
            # Play the next track, if there is one.  If not, the
            # player will stop thanks to the stream stopping above and
            # the state updating when the current packet goes to None.

            # state.track_number counts from 1, not 0
            if self.state.track_number < len(self.current_disc.tracks):
                assert self.state.track_number >= 1
                
                # Start playing the next track (now counting from 0,
                # not 1, so track_number does not have to be incremented...)
                self.streamer = AudioStreamer(self, self.current_disc,
                                              self.state.track_number,
                                              self.rip_process is not None)
                self.device.play_stream(self.streamer.iter_packets())

                # Don't update state here, wait for the packet update
                # to do it

        else:
            raise PlayerError('unexpected state for cmd_next: {0}', self.state)


    def cmd_prev(self, args):
        if self.state.state == State.STOP:
            # Start playing the last track
            assert self.current_disc is not None
            self.play_disc(self.current_disc, len(self.current_disc.tracks) - 1)
            return

        # Stop any current streamer
        if self.streamer:
            self.streamer.shutdown(True)
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
            assert self.state.track_number >= 1
            
            # If the track position is within the first two seconds or
            # the pregap, skip to the previous track.  Otherwise replay
            # this track from the start

            if self.state.position < 2:
                tn = self.state.track_number - 1

                # If this reaches the start of the disc, just stop.
                # Nothing has to be done for that, as update_state()
                # below will react to the stop of the stream.
                if tn == 0:
                    return
                
            else:
                tn = self.state.track_number


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

        if self.streamer:
            self.streamer.shutdown()
            self.streamer = None




    def rip_disc(self, mbd):
        """Set up the process of ripping a disc that's not in the
        database, based on the Musicbrainz Disc object
        """
        
        # Turn Musicbrainz disc into our Disc object
        db_id = self.db.disc_to_db_id(mbd.getId())
        path = self.db.create_disc_dir(db_id)

        disc = model.Disc.from_musicbrainz_disc(
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

        # There shouldn't be a streamer, but if there is stop it
        if self.streamer:
            self.streamer.shutdown()
            self.streamer = None

        # Set up streaming from the start of the selected track
        self.streamer = AudioStreamer(self, disc, track_number,
                                      self.rip_process is not None)
        self.current_disc = disc

        # Initialise state to new disc and WORKING, i.e. we're waiting
        # for the device to tell us it's started playing
        self.state.state = State.WORKING
        self.state.disc_id = disc.disc_id
        self.state.track_number = 0
        self.state.no_tracks = len(disc.tracks)
        self.state.index = 0
        self.state.position = 0
        self.state.ripping = self.rip_process is not None
        
        self.write_state()

        # Finally tell device to start playing packets from this stream
        self.device.play_stream(self.streamer.iter_packets())


    def update_state(self):
        """Check what the audio device is doing and update the state
        according to that.
        """

        # This really needs improvement, as we need to be able to tell
        # the difference between a stream that stopped due to reaching
        # the normal end of the disc, or being aborted.

        p = self.device.get_current_packet()
            
        if p is None:
            pos = 0
        else:
            # Round down
            pos = int(p.rel_pos / self.current_disc.sample_format.rate)


        # Waiting for the first packet.  The case when that packet
        # never arrives is handled above in run_once().
        if self.state.state == State.WORKING:
            if p is not None:
                self.state.state = State.PLAY
                self.state.track_number = p.track_number + 1
                self.state.index = p.index
                self.state.position = pos
                self.write_state()

        # React to updates from the device in both PLAY and PAUSE,
        # since it may lag a bit

        elif self.state.state in (State.PLAY, State.PAUSE):
            # Stream stopped
            if p is None:
                self.state.state = State.STOP
                self.state.track_number = 0
                self.state.index = 0
                self.state.position = 0
                self.write_state()

            # New track or index
            elif (self.state.track_number != p.track.number or
                  self.state.index != p.index):
                self.state.track_number = p.track_number + 1
                self.state.index = p.index
                self.state.position = pos
                self.write_state()

            # Moved backward in track
            elif pos < self.state.position:
                self.state.position = pos
                self.write_state()
                
            # Moved a second (not worth logging)
            elif pos != self.state.position:
                self.state.position = pos
                self.write_state(False)


    def write_state(self, log_state = True):
        # TODO: write to file

        if log_state:
            self.debug('state: {0}', self.state)


    def log(self, msg, *args, **kwargs):
        m = time.strftime('%Y-%m-%d %H:%M:%S ') + msg.format(*args, **kwargs) + '\n'
        self.log_file.write(m)
        self.log_file.flush()

        
    def debug(self, msg, *args, **kwargs):
        if self.log_debug:
            self.log(msg, *args, **kwargs)

    

class AudioStreamer(object):
    """Streamer for audio samples.  Encapsulates a thread reading from
    the file (to handle any IO waits) and a queue for passing samples
    with meta data to the player.  The player can ask the thread to
    stop, typically used when stopping playing or skipping forward or
    backward.
    """
    # Special objects to signal the end of the stream
    class STREAM_ERROR: pass
    class END_OF_STREAM: pass

    # Perhaps make this configurable sometime
    MAX_BUFFER_SECS = 20
    PACKETS_PER_SECOND = 5

    def __init__(self, player, disc, track_number, is_ripping):
        """Set up an audio stream from DISC, starting at TRACK_NUMBER.
        """

        self.player = player
        self.log = player.log
        self.debug = player.debug
        
        # Due to the Big Interpreter Lock we probably don't need any
        # thread signalling at all for these simple flags, but let's
        # play it nice.
        
        self.is_ripping = threading.Event()
        if is_ripping:
            self.is_ripping.set()
            
        self.stop_streamer = threading.Event()
        self.stop_on_skip = threading.Event()

        self.disc = disc
        self.first_track_number = track_number

        self.queue = Queue.Queue(self.PACKETS_PER_SECOND * self.MAX_BUFFER_SECS)
        
        self.thread = threading.Thread(target = self.run_thread)
        self.thread.daemon = True
        self.thread.start()


    def iter_packets(self):
        """Return an iterator over all the packets in the stream.
        There should only be one iterator per stream, otherwise you'll
        get some interesting effects.
        """

        while True:
            if self.stop_streamer.is_set():
                # Empty the queue to ensure that the streamer thread
                # isn't blocking on us and also detects the flag
                try:
                    while True:
                        self.queue.get_nowait()
                except Queue.Empty:
                    pass

                # Inform audio device about the unexpected stop
                if self.stop_on_skip.is_set():
                    raise audio.StreamSkipAbort('skipping tracks')
                else:
                    raise audio.StreamAbort('streamer shutdown by player')


            # Normal case: wait for a packet and output it
            p = self.queue.get()

            # Special values signalling the end of the stream
            if p == self.END_OF_STREAM:
                self.debug('end of audio stream')
                return
            
            elif p == self.STREAM_ERROR:
                self.debug('error in audio stream')
                raise audio.StreamAbort('error in audio stream')

            else:
                yield p
            


    def shutdown(self, skipping = False):
        """Shut down the streamer thread.

        If SKIPPING is true, the stream is shut down due to skpping
        among tracks.
        """

        if skipping:
            self.stop_on_skip.set()
            
        self.stop_streamer.set()


    def rip_finished(self):
        """Call to inform that the any concurrent ripping process is finished."""

        self.is_ripping.clear()


    def run_thread(self):
        end_of_stream = self.STREAM_ERROR
        try:
            self.debug('{0}: streamer started for {1} track {2}',
                       self.thread.name, self.disc, self.first_track_number)


            # Construct full path to data file and open it

            db_id = self.player.db.disc_to_db_id(self.disc.disc_id)
            path = os.path.join(
                self.player.db.get_disc_dir(db_id),
                self.disc.data_file_name)
                    
            self.debug('{0}: opening file {1}',
                       self.thread.name, path)
                    

            self.audio_file = None

            # Retry opening file if the ripping process is in progress
            # and might not have had time to create it yet

            while self.audio_file is None:
                # Obey commands to stop - typically this could only
                # happen if the ripping process dies without managing
                # to read anything
                if self.stop_streamer.is_set():
                    return

                try:
                    self.audio_file = open(path, 'rb')
                except IOError, e:
                    if e.errno == errno.ENOENT and self.is_ripping:
                        self.debug('{0}: retrying opening file {1}',
                                   self.thread.name, path)
                        time.sleep(0.5)
                    else:
                        self.log('{0}: error opening file {1}: {2}',
                                 self.thread.name, path, e)
                        return


            # Iterate over all packets, reading data into them

            for p in audio.AudioPacket.iterate(self.disc,
                                               self.first_track_number,
                                               self.PACKETS_PER_SECOND):

                # Obey commands to stop, treating this as a normal end
                # of stream
                if self.stop_streamer.is_set():
                    end_of_stream = self.END_OF_STREAM
                    return

                try:
                    self.read_data_into_packet(p)
                except IOError, e:
                    self.log('{0}: error reading from file {1}: {2}',
                             self.thread.name, path, e)
                    return

                # Finally send out packet to consumer
                self.queue.put(p)

            # end of loop, handle next packet

            # If we got here, then all streamed fine
            end_of_stream = self.END_OF_STREAM

        finally:
            self.queue.put(end_of_stream)
            self.debug('{0}: streamer shutting down on {1}',
                       self.thread.name, end_of_stream.__name__)
            self.player = None
            self.log = None
            self.player = None


    def read_data_into_packet(self, p):
        """Thread helper method for populating data into packet P."""

        length = p.length * self.disc.sample_format.sample_bytes

        if p.file_pos is None:
            # Silence, so send on null bytes to player
            p.data = '\0' * length

        else:
            file_pos = p.file_pos * self.disc.sample_format.sample_bytes
            
            self.audio_file.seek(file_pos)

            p.data = self.audio_file.read(length)
            length -= len(p.data)
            file_pos += len(p.data)
            
            # If we didn't get all data, iterate with a timeout until
            # it's all been read or the ripping process has stopped.
            # This is not very efficient, and there's a small race
            # condition at the end of the disc, but this should be
            # very rare so keep it unoptimised for now.

            while length > 0 and self.is_ripping:
                time.sleep(1)
                
                self.audio_file.seek(file_pos)
                d = self.audio_file.read(length)
                length -= len(d)
                file_pos += len(d)

                p.data += d
                        
            # Still didn't get all data, treat it as an exception
            if length > 0:
                raise IOError('unexpected end of file, expected at least {0} bytes'
                              .format(length))
        

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
        
