# codplayer - ZeroMQ support
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Use ZeroMQ to publish player state and accept commands.
"""

import time
import threading

import zmq

from . import state
from . import command
from . import model
from . import serialize

#
# Publishing state over ZeroMQ
#

class ZMQPublisherFactory(state.PublisherFactory):
    def __init__(self, address, command_factory = None):
        super(ZMQPublisherFactory, self).__init__()
        self.address = address
        self.command_factory = command_factory

    def publisher(self, player):
        return ZMQPublisher(player, self.address)

    def getter(self):
        if self.command_factory:
            return ZMQStateGetter(self.command_factory.client())
        else:
            return None

    def subscriber(self):
        return ZMQSubscriber(self.address)


class ZMQPublisher(state.StatePublisher):
    def __init__(self, player, address):
        super(ZMQPublisher, self).__init__()
        self.log = player.log
        self.debug = player.debug

        self.lock = threading.Lock()

        self.socket = player.zmq_context.socket(zmq.PUB)
        self.socket.set_hwm(10)

        self.log('publishing state on {0}', address)
        self.socket.bind(address)

    def update_state(self, state):
        try:
            with self.lock:
                self.socket.send_multipart(['state', serialize.get_jsons(state)])
        except zmq.ZMQError as e:
            self.log('zeromq: error publishing state: {0}', e)

    def update_rip_state(self, rip_state):
        try:
            with self.lock:
                self.socket.send_multipart(['rip_state', serialize.get_jsons(rip_state)])
        except zmq.ZMQError as e:
            self.log('zeromq: error publishing rip state: {0}', e)

    def update_disc(self, disc):
        try:
            with self.lock:
                self.socket.send_multipart(['disc', serialize.get_jsons(disc)])
        except zmq.ZMQError as e:
            self.log('zeromq: error publishing state: {0}', e)


class ZMQStateGetter(state.StateGetter):
    def __init__(self, client):
        self.client = client

    def get_state(self, timeout = None):
        try:
            return self.client.send('state', [], timeout = timeout)
        except (command.CommandError, command.ClientError) as e:
            raise state.StateError(str(e))

    def get_rip_state(self, timeout = None):
        try:
            return self.client.send('rip_state', [], timeout = timeout)
        except (command.CommandError, command.ClientError) as e:
            raise state.StateError(str(e))

    def get_disc(self, timeout = None):
        try:
            return self.client.send('source', [], timeout = timeout)
        except (command.CommandError, command.ClientError) as e:
            raise state.StateError(str(e))


class ZMQSubscriber(state.StateSubscriber):
    def __init__(self, address):
        super(ZMQSubscriber, self).__init__()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.set_hwm(10)
        self.socket.set(zmq.SUBSCRIBE, '')
        self.socket.connect(address)

    def iter(self, timeout = None):
        if timeout is not None:
            end = time.time() + timeout
        else:
            end = None

        while True:
            if end is not None:
                timeout_ms = max(0, int(end - time.time()) * 1000)
            else:
                timeout_ms = None

            try:
                ev = self.socket.poll(timeout_ms, zmq.POLLIN)
                if not ev:
                    return

                msg = self.socket.recv_multipart(copy = True)
            except zmq.ZMQError as e:
                raise state.StateError('zeromq: error receiving state: {0}'.format(e))

            obj = self.parse_message(msg)
            if obj:
                yield obj


    def parse_message(self, msg):
        try:
            if msg[0] == 'state':
                cls = state.State
                json = msg[1]
            elif msg[0] == 'rip_state':
                cls = state.RipState
                json = msg[1]
            elif msg[0] == 'disc':
                cls = model.ExtDisc
                json = msg[1]
            else:
                # It's ok to get unknown stuff
                return None
        except IndexError:
            raise state.StateError('zeromq: missing message parts: {0}'.format(msg))

        try:
            return serialize.load_jsons(cls, json)
        except serialize.LoadError, e:
            raise state.StateError('zeromq: malformed message object: {0}'.format(msg))


#
# Commands over ZeroMQ
#

class ZMQCommandFactory(command.CommandFactory):
    """Factory for recieving and sending commands over a Unix fifo."""

    def __init__(self, address):
        super(ZMQCommandFactory, self).__init__()
        self.address = address

    def server(self, player):
        return ZMQServer(player, self.address)

    def client(self):
        return ZMQClient(self.address)


class ZMQServer(command.CommandServer):
    def __init__(self, player, address):
        player.log('receiving commands at {0}', address)
        self.socket = player.zmq_context.socket(zmq.REP)
        self.socket.bind(address)

        super(ZMQServer, self).__init__(player)

    def run(self):
        try:
            while True:
                self.run_once()
        finally:
            self.log('ZMQ command server loop stopped unexpectedly')

    def run_once(self):
        cmd = self.socket.recv_multipart()
        try:
            result = self.send(cmd)
        except command.CommandError as e:
            self.socket.send_multipart(['error', str(e)])
        else:
            self.socket.send_multipart(result)


class ZMQClient(command.CommandClient):
    def __init__(self, address):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.connect(address)


    def send(self, cmd, args, timeout = None):
        cmd_args = [cmd]
        cmd_args.extend(args)

        if timeout is not None:
            end = time.time() + timeout
        else:
            end = None

        while True:
            if end is not None:
                timeout_ms = max(0, int(end - time.time()) * 1000)
            else:
                timeout_ms = None

            try:
                if cmd_args:
                    ev = self.socket.poll(timeout_ms, zmq.POLLOUT)
                    if not ev:
                        raise command.ClientError('timeout sending command to player')

                    self.socket.send_multipart(cmd_args)
                    cmd_args = None

                else:
                    ev = self.socket.poll(timeout_ms, zmq.POLLIN)
                    if not ev:
                        raise command.ClientError('timeout recieving response from player')

                    msg = self.socket.recv_multipart()
                    return self.parse_message(msg)

            except zmq.ZMQError as e:
                raise command.ClientError('zeromq: error calling player: {0}'.format(e))


    def parse_message(self, msg):
        if len(msg) < 1:
            raise command.ClientError('got empty response: {0}'.format(msg))

        if msg[0] == 'state':
            if len(msg) < 2:
                raise command.ClientError('missing state in response: {0}'.format(msg))

            try:
                return state.State.from_string(msg[1])
            except serialize.LoadError as e:
                raise command.ClientError('error deserializing state: {0}'.format(e))

        elif msg[0] == 'rip_state':
            if len(msg) < 2:
                raise command.ClientError('missing rip state in response: {0}'.format(msg))

            try:
                return state.RipState.from_string(msg[1])
            except serialize.LoadError as e:
                raise command.ClientError('error deserializing rip state: {0}'.format(e))

        elif msg[0] == 'disc':
            if len(msg) < 2:
                raise command.ClientError('missing disc in response: {0}'.format(msg))

            try:
                return serialize.load_jsons(model.ExtDisc, msg[1])
            except serialize.LoadError as e:
                raise command.ClientError('error deserializing disc: {0}'.format(e))

        elif msg[0] == 'ok':
            return None

        elif msg[0] == 'error':
            if len(msg) < 2:
                raise command.ClientError('missing details in error response: {0}'.format(msg))

            raise command.CommandError(msg[1])
        else:
            raise command.ClientError('unexpected return type: {0}'.format(msg))
