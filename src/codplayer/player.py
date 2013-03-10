# codplayer - player state 
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes implementing the player core and it's state.

The unit of time in all objects is one sample.
"""

import select


class PlayerError(Exception):
    pass

class State(object):
    """Player state as visible to external users.
    """

    class NO_DISC:
        valid_commands = 'disc'

    class PLAY:
        valid_commands = ('pause', 'next', 'prev', 'stop', 'eject')

    class PAUSE:
        valid_commands = ('play', 'next', 'prev', 'stop', 'eject')

    class STOP:
        valid_commands = ('play', 'eject')

    def __init__(self):
        self.state = self.NO_DISC
        self.ripping = False
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
    


class Player(object):

    def __init__(self, cfg, database, log_file, control_file):
        self.cfg = cfg
        self.db = database
        self.log_file = log_file
        self.log_debug = True
        self.control = CommandReader(control_file)
        self.state = State()

        self.poll = select.poll()
        self.poll.register(self.control, select.POLLIN)

    def run(self):
        while True:
            self.run_once(1000)
            

    def run_once(self, ms_timeout):
        fds = self.poll.poll(ms_timeout)

        for fd, event in fds:
            if fd == self.control.fileno():
                for cmd_args in self.control.handle_data():
                    self.handle_command(cmd_args)

                    
    def handle_command(self, cmd_args):
        self.debug('got command: {0}', cmd_args)


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

    def __init__(self, control_file):
        self.file = control_file
        self.buffer = ''

    def fileno(self):
        """For compatibility with poll()"""
        return self.file.fileno()

    def handle_data(self):
        """Call when poll() says there's data to read on the control file.

        Acts as an iterator, generating all received commands
        (typically only one, though).  The command is split into an
        argv style list.
        """
        
        d = self.file.read(500)
        if not d:
            raise PlayerError('unexpected close of control file')

        self.buffer += d

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

        
