# codplayer - player command input
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes for handling command input to the player.
"""


from . import state
from . import model
from . import serialize


class CommandError(Exception):
    """Raised when executing a command resulted in an error, such as not
    being allowed in the current player state.
    """


class ClientError(Exception):
    """Raised when the client couldn't send a command to the server."""


class AsyncCommandRPCClient(object):
    """Asynchronous command RPC client, running in an IO loop.
    """

    def __init__(self, async_rpc_client, on_response = None, on_error = None):
        self._client = async_rpc_client
        self._default_on_response = on_response
        self._default_on_error = on_error

    # TODO: define methods for all commands

    def call(self, cmd, args = [], on_response = None, on_error = None):
        """Generic method to call any command with a list of arguments.

        The on_response callback is called on a normal response, with
        one argument: the response deserialised to a State, RipState,
        ExtDisc, or a plain python object, depending on the type.

        Thge on_error callback is called if the call fails, with one
        argument: an exception describing the error.
        """
        cmd_args = [cmd]
        cmd_args.extend(args)

        self._client.call(
            cmd_args,
            lambda msg, error: self._callback(
                msg, error,
                on_response or self._default_on_response,
                on_error or self._default_on_error))


    def _callback(self, reply_msg, error, on_response, on_error):
        reply_obj = None
        if reply_msg:
            try:
                reply_obj = self._parse_message(reply_msg)
            except (ClientError, CommandError) as e:
                error = e

        if error:
            if on_error:
                on_error(error)
        else:
            if on_response:
                on_response(reply_obj)


    def _parse_message(self, msg):
        if len(msg) < 1:
            raise ClientError('got empty response: {0}'.format(msg))

        if msg[0] == 'state':
            if len(msg) < 2:
                raise ClientError('missing state in response: {0}'.format(msg))

            try:
                return state.State.from_string(msg[1])
            except serialize.LoadError as e:
                raise ClientError('error deserializing state: {0}'.format(e))

        elif msg[0] == 'rip_state':
            if len(msg) < 2:
                raise ClientError('missing rip state in response: {0}'.format(msg))

            try:
                return state.RipState.from_string(msg[1])
            except serialize.LoadError as e:
                raise ClientError('error deserializing rip state: {0}'.format(e))

        elif msg[0] == 'disc':
            if len(msg) < 2:
                raise ClientError('missing disc in response: {0}'.format(msg))

            try:
                return serialize.load_jsons(model.ExtDisc, msg[1])
            except serialize.LoadError as e:
                raise ClientError('error deserializing disc: {0}'.format(e))

        elif msg[0] == 'ok':
            try:
                return json.loads(msg[1])
            except ValueError as e:
                raise ClientError('error deserializing response: {0}'.format(e))
            except IndexError:
                return None

        elif msg[0] == 'error':
            if len(msg) < 2:
                raise ClientError('missing details in error response: {0}'.format(msg))

            raise CommandError(msg[1])
        else:
            raise ClientError('unexpected return type: {0}'.format(msg))



class CommandReader(object):
    """Given read bytes as input, it collects whole lines and yields argv
    lists when a complete command has been read.
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

