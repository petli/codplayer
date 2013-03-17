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
import select
import subprocess
import time
import threading
import Queue

from musicbrainz2 import disc as mb2_disc

from . import db, model


class PlayerError(Exception):
    pass

class State(object):
    """Player state as visible to external users.
    """

    class NO_DISC:
        valid_commands = ('quit', 'disc')

    class PLAY:
        valid_commands = ('quit', 'pause', 'play_pause',
                          'next', 'prev', 'stop', 'eject')

    class PAUSE:
        valid_commands = ('quit', 'play', 'play_pause',
                          'next', 'prev', 'stop', 'eject')

    class STOP:
        valid_commands = ('quit', 'play', 'play_pause', 'eject')


    def __init__(self):
        self.state = self.NO_DISC
        self.db_id = None
        self.track_number = 0
        self.no_tracks = 0
        self.index = 0
        self.position = 0
        self.sample_format = None


    @classmethod
    def from_string(cls, json):
        pass

    def to_string(self):
        pass
    
    def __str__(self):
        return self.state.__name__


class Player(object):

    def __init__(self, cfg, database, log_file, control_fd):
        self.cfg = cfg
        self.db = database
        self.log_file = log_file
        self.log_debug = True

        self.rip_process = None

        self.streamer = None
        self.current_disc = None
        self.current_packet = None

        self.control = CommandReader(control_fd)
        self.state = State()

        self.poll = select.poll()
        self.poll.register(self.control, select.POLLIN)


    def run(self):
        while True:
            # TODO: add general exception handling here
            self.run_once(1000)
            

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

        # Set state to stopped 
        self.state.state = State.STOP
        self.state.track_number = 0
        self.state.index = 0
        self.state.position = 0

        self.write_state()


    def cmd_play(self, args):
        if self.state.state == State.STOP:
            # Just restart playing
            assert self.current_disc is not None
            self.play_disc(self.current_disc)

        else:
            raise PlayerError('unexpected state for cmd_play: {0}', self.state)


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


    def play_disc(self, disc):
        """Start playing disc from the database"""

        self.log('playing disk: {0}', disc)

        # There shouldn't be a streamer, but if there is stop it
        if self.streamer:
            self.streamer.shutdown()
            self.streamer = None

        # Set up streaming from position 0
        self.streamer = AudioStreamer(self, disc, 0)
        self.current_disc = disc

        # Initialise state to new disc
        self.state.state = self.state.PLAY
        self.state.db_id = self.db.disc_to_db_id(disc.disc_id)
        self.state.track_number = 1 # not counting from 0 here
        self.state.no_tracks = len(disc.tracks)
        self.state.index = 1 # first pregap/intro is skipped
        self.state.position = 0
        self.state.sample_format = disc.sample_format
        
        self.write_state()


    def write_state(self):
        # TODO: write to file
        self.debug('state: {0}', self.state.__dict__)


    def log(self, msg, *args, **kwargs):
        m = time.strftime('%Y-%m-%d %H:%M:%S ') + msg.format(*args, **kwargs) + '\n'
        self.log_file.write(m)
        self.log_file.flush()

        
    def debug(self, msg, *args, **kwargs):
        if self.log_debug:
            self.log(msg, *args, **kwargs)

    

class AudioPacket(object):
    """A packet of audio data coming from a single track and index.

    It has the following attributes (all positions and lengths count
    samples, as usual):
    
    track: a model.Track object 

    index: the track index counting from 0

    abs_pos: the track position from the start of index 0

    rel_pos: the track position from the start of index 1

    file_pos: the file position for the first track, or None if the
    packet should be silence

    length: number of samples in the packet

    data: sample data
    """

    def __init__(self, track, abs_pos, length):
        self.track = track

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


class AudioPacketizer(object):
    """Utility class for splitting an audio file into packets.

    This call will ensure that no packets cross an index or track
    boundary, and will also obey any edits to the disc.

    It will not, however, read any samples from disc, just tell the
    calling code what to read.
    """

    def __init__(self, disc, track_number, packets_per_second):
        """Set up packetizing DISC, starting at TRACK_NUMBER index 1.

        The maximum size of the packets returned are controlled by
        packets_per_second.
        """
        assert track_number < len(disc.tracks)

        self.disc = disc
        self.track_number = track_number

        # Mock up a packet that ends at the start of index 1
        self.prev_packet = AudioPacket(
            track, track.pregap_offset, 0)


    def get_next_packet(self):
        """Return the next packet, or None if the end of the disc has
        been reached.
        """

        return None



                                
class AudioStreamer(object):
    """Streamer for audio samples.  Encapsulates a thread reading from
    the file (to handle any IO waits) and a queue for passing samples
    with meta data to the player.  The player can ask the thread to
    stop, typically used when stopping playing or skipping forward or
    backward.
    """
    
    # Perhaps make this configurable sometime
    MAX_BUFFER_SECS = 20
    PACKETS_PER_SECOND = 5

    def __init__(self, player, disc, track_number):
        """Set up an audio stream from DISC, starting at track_number.
        """

        self.player = player

        self.disc = disc
        self.track_number = 0
        self.track_index = 1 # skip any pregap/index
        
        self.packet_sample_size = (
            disc.sample_format.rate / self.PACKETS_PER_SECOND)
        self.packet_byte_size = (
            self.packet_sample_size * disc.sample_format.sample_bytes)

        self.queue = Queue.Queue(self.PACKETS_PER_SECOND * self.MAX_BUFFER_SECS)
        self.underflow_logged = False
        
        self.keep_running = True

        self.thread = threading.Thread(target = self.run_thread)
        self.thread.daemon = True
        self.thread.start()


    def get_packet(self):
        """Return the next queued audio packet, or None if the queue is empty.
        """
        try:
            packet = self.queue.get_nowait()
            self.underflow_logged = False
            return packet
        except Queue.Empty:
            if not self.underflow_logged:
                self.underflow_logged = True
                self.debug('underflow getting audio from thread {0}', self.thread.name)
            return None
        

    def shutdown(self):
        """Shut down the streamer thread, discarding any queued packets.
        """

        # Assume the global interpreter lock allows us to flip this flag safely
        self.keep_running = False

        # Empty queue to ensure that the thread sees the flag
        try:
            while True:
                self.queue.get_nowait()
        except Queue.Empty:
            pass
                

    def run_thread(self):
        self.player.debug('streamer thread {2} started for {0} track {1}',
                          self.disc, self.track_index, self.thread.name)

        while self.keep_running:
            time.sleep(1)

        self.player.debug('streamer thread {0} shutting down', self.thread.name)
        self.player = None

        
            
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
        
