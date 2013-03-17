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
        self.track_num = 0
        self.no_tracks = 0
        self.index = 0
        self.position = 0
        self.format = None


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
            # Nope, turn it into a temporary Disc object good enough
            # for playing and start the ripping process
            disc = model.Disc.from_musicbrainz_disc(mbd)
            rip_started = self.rip_disc(disc)
            if not rip_started:
                return

        self.play_disc(disc)


    def rip_disc(self, disc):
        """Set up the process of ripping a disc that's not in the
        database.
        """
        
        self.log('ripping new disk: {0}', disc)

        db_id = self.db.disc_to_db_id(disc.disc_id)
        path = self.db.create_disc_dir(db_id)

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
            return False

        return True


    def play_disc(self, disc):
        """Start playing disc from the database"""

        self.log('playing disk: {0}', disc)
        # TODO: do this...
        

    def log(self, msg, *args, **kwargs):
        self.log_file.write(msg.format(*args, **kwargs))
        self.log_file.write('\n')
        self.log_file.flush()

        
    def debug(self, msg, *args, **kwargs):
        if self.log_debug:
            self.log(msg, *args, **kwargs)

    
                                
            
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
        
