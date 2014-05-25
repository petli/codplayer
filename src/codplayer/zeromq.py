# codplayer - ZeroMQ support
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Use ZeroMQ to publish player state and accept commands.
"""

import time

import zmq

from . import state
from . import model
from . import serialize

class ZMQPublisherFactory(state.PublisherFactory):
    def __init__(self, address):
        super(ZMQPublisherFactory, self).__init__()
        self.context = zmq.Context()
        self.address = address

    def publisher(self, player):
        return ZMQPublisher(player, self.context, self.address)

    def getter(self):
        return None

    def subscriber(self):
        return ZMQSubscriber(self.context, self.address)


class ZMQPublisher(state.StatePublisher):
    def __init__(self, player, context, address):
        super(ZMQPublisher, self).__init__()
        self.log = player.log
        self.debug = player.debug

        self.socket = context.socket(zmq.PUB)
        self.socket.set_hwm(10)

        self.log('publishing state on {0}', address)
        self.socket.bind(address)

    def update_state(self, state):
        try:
            self.socket.send_multipart(['state', serialize.get_jsons(state)])
        except zmq.ZMQError as e:
            self.log('zeromq: error publishing state: {0}', e)

    def update_disc(self, disc):
        try:
            self.socket.send_multipart(['disc', serialize.get_jsons(disc)])
        except zmq.ZMQError as e:
            self.log('zeromq: error publishing state: {0}', e)


class ZMQSubscriber(state.StateSubscriber):
    def __init__(self, context, address):
        super(ZMQSubscriber, self).__init__()
        self.socket = context.socket(zmq.SUB)
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

