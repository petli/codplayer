# codplayer - player command input
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes for handling command input to the player.
"""

import sys
import os
import errno
import select
import threading
import zmq


class CommandError(Exception):
    """Raised when executing a command resulted in an error, such as not
    being allowed in the current player state.
    """


class ClientError(Exception):
    """Raised when the client couldn't send a command to the server."""



class CommandFactory(object):

    """Base class for command factory implementations."""

    def server(self, player):
        """Create a command server for a Player.  This will be called after
        forking the daemon, but before dropping any privs.
        """
        raise NotImplementedError()

    def client(self):
        raise NotImplementedError()


class CommandServer(object):
    """Base class for command servers running inside codplayerd.  This is
    mostly provided for convenience to connect to the player command
    endpoint and kick off a thread running the command server loop, so
    it's not strictly necessary to subclass this.
    """

    def __init__(self, player):
        self.log = player.log
        self.debug = player.debug

        self.player_socket = player.zmq_context.socket(zmq.REQ)
        self.player_socket.connect(player.COMMAND_ENDPOINT)

        thread = threading.Thread(target = self.run,
                                  name = self.__class__.__name__)
        thread.daemon = True
        thread.start()


    def send(self, cmd_args):
        """Send a command to the player, returning the result as-is."""
        self.player_socket.send_multipart(cmd_args)
        return self.player_socket.recv_multipart()


    def run(self):
        """Infinite loop reading commands."""
        raise NotImplementedError()


class CommandClient(object):
    """Base class for sending commands to the server.  If the client
    supports it, it will return the new state object or raise
    CommandError, otherwise will always return None.
    """

    def send(self, cmd, args, timeout = None):
        raise NotImplementedError()



class FifoCommandFactory(CommandFactory):
    """Factory for recieving and sending commands over a Unix fifo."""

    def __init__(self, fifo_path):
        super(FifoCommandFactory, self).__init__()
        self.fifo_path = fifo_path

    def server(self, player):
        return FifoServer(player, self.fifo_path)

    def client(self):
        return FifoClient(self.fifo_path)


class FifoServer(CommandServer):
    def __init__(self, player, fifo_path):
        # Always recreate the fifo, to avoid any problems with
        # lingering processes or malcreated fifos
        try:
            os.unlink(fifo_path)
        except OSError:
            pass

        try:
            os.mkfifo(fifo_path)
            self.fd = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)

            # To avoid getting an EOF in the reader code when the
            # processes sending commands closes the fifo, open the
            # fifo for writing too to ensure that there's always a
            # writer process.
            os.open(fifo_path, os.O_WRONLY)

            self.poll = select.poll()
            self.poll.register(self.fd, select.POLLIN)

        except OSError, e:
            raise ClientError('error creating and opening fifo {0}: {1}'.format(fifo_path, e))

        player.log('reading commands from fifo: {0}', fifo_path)
        self.reader = CommandReader()

        super(FifoServer, self).__init__(player)

    def run(self):
        try:
            while True:
                self.run_once()
        finally:
            self.log('fifo command server loop stopped unexpectedly')

    def run_once(self):
        for fd, event in self.poll.poll():
            if fd == self.fd:
                data = os.read(self.fd, 500)
                for cmd_args in self.reader.handle_data(data):
                    try:
                        self.send(cmd_args)
                    except CommandError:
                        pass # already logged by Player


class FifoClient(CommandClient):
    def __init__(self, fifo_path):
        self.fifo_path = fifo_path

    def send(self, cmd, args, timeout = None):
        full = [cmd]
        full.extend(args)

        try:
            fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, ' '.join(full) + '\n')
            os.close(fd)
        except OSError, e:
            if e.errno == errno.ENXIO:
                raise ClientError('error sending command to {0}: no deamon listening'
                                   .format(self.fifo_path))
            elif e.errno == errno.ENOENT:
                raise ClientError('error sending command to {0}: no such fifo'
                                   .format(self.fifo_path))
            else:
                raise ClientError('error sending command to fifo: {0}'.format(e))


class StdinCommandFactory(CommandFactory):
    """Used by player in debug mode to accept commands on stdin."""

    def server(self, player):
        return StdinServer(player)


class StdinServer(CommandServer):
    def __init__(self, player):
        player.log('reading commands on stdin')
        self.reader = CommandReader()

        super(StdinServer, self).__init__(player)

    def run(self):
        try:
            while True:
                self.run_once()
        finally:
            self.log('stdin command server loop stopped unexpectedly')

    def run_once(self):
        data = os.read(0, 500)
        for cmd_args in self.reader.handle_data(data):
            try:
                self.send(cmd_args)
            except CommandError:
                pass # already logged by Player


class CommandReader(object):
    """Given read bytes as input, it collects whole lines and yields argv
    lits when a complete command has been read.
    """

    def __init__(self):
        self.buffer = ''

    def handle_data(self, data):
        """Add data to the command reader.

        Acts as an iterator, generating all received commands
        (typically only one, though).  The command is split into an
        argv style list.
        """

        self.buffer += data

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

