# codplayer - Message hub core
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""This module provides a thin message hub abstractions on top of
ZeroMQ to make it easy to wire together different components and
daemons without having to know exactly how they are deployed or
requiring to have a central hub instance.

Nothing in here is specific to codplayer, so this could (should!) be
split out into a standalone package.

It relies on IOLoop, either the full Tornado one or the mini IOLoop
provided by pyzmq.

Other code should use zerohub.IOLoop to access the Tornado (or Mini
Tornado) IOLoop class, and zerohub.IOLoop().instance() to get the
default instance.
"""

import zmq
from zmq.eventloop.zmqstream import ZMQStream

# Rely on the ZeroMQ mini-version of the Tornado ioloop
from zmq.eventloop import ioloop
#ioloop.install()

from zmq.eventloop.ioloop import IOLoop


# Common context
_context = None
def get_context():
    global _context
    if _context is None:
        _context = zmq.Context()
    return _context

class UndefinedSenderError(Exception): pass

class Channel(object):
    """Common message channel interface for the specific kinds of channels
    defined as subclasses.
    """

    def get_receiver_stream(self, subscriptions, io_loop = None):
        """Return a ZMQStream for receiving messages from this channel.

        subscriptions is an iterable of event names that the stream
        should subscribe to (if applicable).
        """
        raise NotImplementedError()

    def get_sender_stream(self, name, io_loop = None):
        """Return a ZMQStream for sending messages to this channel
        for a named sender.
        """
        raise NotImplementedError()

    def get_client_rpc_stream(self, io_loop = None):
        """Return a ZMQStream for client-side RPC messaging to a channel.
        """
        raise NotImplementedError()

    def dispatch_message(self, stream, callbacks, fallback, receiver, msg_parts):
        """Dispatch a received message to the correct callback or callbacks,
        using the channel semantics.
        """
        raise NotImplementedError()


class Topic(Channel):
    """An event topic supporting any number of publishers and subscribers.
    """
    def __init__(self, name = None, **pub_addresses):
        """Define a topic, listing all the publishers and the ZeroMQ socket
        address of each as key-value pairs.

        MessageHandler event names have the same semantics as ZeroMQ
        PUB/SUB sockets, i.e. they match if the name of the received
        event starts with the same sequence of characters.
        """
        self.name = name
        self._pub_addresses = pub_addresses


    def __str__(self):
        return '<Topic {0} on {1}>'.format(
            self.name or id(self),
            ', '.join(['{}={}'.format(k, v)
                       for k, v
                       in self._pub_addresses.iteritems()]))


    def get_receiver_stream(self, subscriptions, io_loop = None):
        """Return a SUB socket stream.
        """
        socket = get_context().socket(zmq.SUB)
        socket.set_hwm(10)

        for address in self._pub_addresses.itervalues():
            socket.connect(address)

        for sub in subscriptions:
            socket.set(zmq.SUBSCRIBE, sub)

        return ZMQStream(socket, io_loop)


    def get_sender_stream(self, name, io_loop = None):
        """Return a PUB socket stream.
        """
        try:
            address = self._pub_addresses[name]
        except KeyError:
            raise UndefinedSenderError(name)

        socket = get_context().socket(zmq.PUB)
        socket.set_hwm(10)
        socket.bind(address)

        return ZMQStream(socket, io_loop)


    def dispatch_message(self, stream, callbacks, fallback, receiver, msg_parts):
        """Send messages to all the callbacks matching a prefix of the message name.
        """
        msg_name = msg_parts[0]
        for sub, func in callbacks.iteritems():
            if msg_name.startswith(sub):
                fallback = None
                func(receiver, msg_parts)

        if fallback:
            fallback(receiver, msg_parts)


class RPC(Channel):
    """A request-response queue where any number of clients
    can send requests to a single service and receive a response.
    """
    def __init__(self, address, name = None):
        """Define an RPC queue, listening on address.

        MessageHandler event names must match the received event name
        exactly to invoke a callback.
        """
        self.name = name
        self._address = address


    def __str__(self):
        return '<RPC {0} on {1}>'.format(self.name or id(self), self._address)


    def get_receiver_stream(self, subscriptions, io_loop = None):
        """Return a REP socket stream.
        """
        socket = get_context().socket(zmq.REP)
        socket.bind(self._address)
        return ZMQStream(socket, io_loop)


    def get_client_rpc_stream(self, io_loop = None):
        """Return a REQ socket stream.
        """
        socket = get_context().socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(self._address)
        return ZMQStream(socket, io_loop)


    def dispatch_message(self, stream, callbacks, fallback, receiver, msg_parts):
        """Send messages to all the callbacks matching a prefix of the message name.
        """
        func = callbacks.get(msg_parts[0], fallback)
        reply = func(receiver, msg_parts) if func else None

        if reply is None:
            reply = ['']
        stream.send_multipart(reply)



class Queue(Channel):
    """A one-way queue where any number of clients can send messages
    (typically commands) to a single service.
    """
    def __init__(self, address, name = None):
        """Define a one-way queue, listening on address.

        MessageHandler event names must match the received event name
        exactly to invoke a callback.
        """
        self.name = name
        self._address = address


    def __str__(self):
        return '<Queue {0} on {1}>'.format(self.name or id(self), self._address)


    def get_receiver_stream(self, subscriptions, io_loop = None):
        """Return a PULL socket stream.
        """
        socket = get_context().socket(zmq.PULL)
        socket.bind(self._address)
        return ZMQStream(socket, io_loop)


    def get_sender_stream(self, name, io_loop = None):
        """Return a PUSH socket stream.
        """
        socket = get_context().socket(zmq.PUSH)
        socket.connect(self._address)
        return ZMQStream(socket, io_loop)


    def dispatch_message(self, stream, callbacks, fallback, receiver, msg_parts):
        """Send messages to all the callbacks matching a prefix of the message name.
        """
        func = callbacks.get(msg_parts[0], fallback)
        if func:
            func(receiver, msg_parts)


class Receiver(object):
    """A message receiver for a channel."""

    def __init__(self, channel, name = None, io_loop = None,
                 callbacks = {}, fallback = None, **kw_callbacks):
        """Create a message receiver for a channel, passing received messages
        to callback functions. The callbacks are called with two
        argument:

        callback(receiver, message_parts)

        The first argument is the receiver object.  If event callbacks
        need to interact with the ioloop it should use the
        receiver.io_loop object.

        The second argument is the message parts as returned from
        zqm.socket.recv_multipart().

        RPC message callbacks should return a list of message parts to
        send as a response.

        Callbacks can be defined either in the callbacks dict (if the
        event names contain non-symbol characters) or as key-value
        parameters.  If a name is defined in both places the dict has
        precedence.

        The semantics of the callback names are specific to each kind
        of channel.

        If no callback match and fallback is provided, it is called
        instead.
        """
        self.io_loop = io_loop or IOLoop.instance()
        self.channel = channel
        self.name = name
        self._callbacks = kw_callbacks
        self._callbacks.update(callbacks)
        self._fallback = fallback
        self._stream = channel.get_receiver_stream(
            callbacks.iterkeys(), io_loop)
        self._stream.on_recv(self._on_message)


    def __str__(self):
        return '<Receiver {0} for {1}>'.format(
            self.name or id(self), str(self.channel))


    def close(self):
        """Close the channel.
        """
        self.io_loop.add_callback(self._do_close)


    def _do_close(self):
        if self._stream:
            self._stream.close()
            self._stream = None


    def _on_message(self, msg_parts):
        """Callback when receiving a message on the channel.  Dispatches the
        message to the matching callback (or callbacks).
        """
        assert len(msg_parts) > 0
        self.channel.dispatch_message(
            self._stream, self._callbacks, self._fallback, self, msg_parts)


class AsyncSender(object):
    """An asynchronous message sender to Topic and Queue channels.
    """

    def __init__(self, channel, name = None, io_loop = None):
        """Create a message sender to a channel.

        Topic channels require a sender name to be specified, but it
        is nice to provide a sender name for other channels too.
        """
        self.io_loop = io_loop or IOLoop.instance()
        self.channel = channel
        self.name = name
        self._stream = channel.get_sender_stream(name, io_loop)


    def __str__(self):
        return '<AsyncSender {0} for {1}>'.format(
            self.name or id(self), str(self.channel))


    def send(self, msg):
        """Send a message to the channel.
        """
        self.io_loop.add_callback(lambda: self._stream.send(msg))

    def send_multipart(self, msg_parts):
        """Send a multipart message to the channel.
        """
        self.io_loop.add_callback(lambda: self._stream.send_multipart(msg_parts))

    def close(self, linger = None):
        """Close the channel.
        """
        self.io_loop.add_callback(lambda: self._do_close(linger))

    def _do_close(self, linger):
        if self._stream:
            self._stream.close(linger = linger)
            self._stream = None


class AsyncRPCClient(object):
    """Asynchronous client for RPC channels.
    """

    def __init__(self, channel, name = None, io_loop = None):
        """Create a message sender to a channel.

        Topic channels require a sender name to be specified, but it
        is nice to provide a sender name for other channels too.
        """
        self.io_loop = io_loop or IOLoop.instance()
        self.channel = channel
        self.name = name
        self._stream = channel.get_client_rpc_stream(io_loop)

        # Since REQ sockets enforce a strict
        # send->receive->send->receive pattern, we must be careful to
        # not receive anything until a message has been sent, and vice
        # versa, not send anything while waiting for receiving the
        # response.  This is handled by a queue and an interlocking
        # set of send/receive callbacks.  Having a receive callback
        # tells the ZMQStream to receive, so it can only be installed
        # when in that state.  The send callback can always be there.

        self._queue = []
        self._stream.on_send(self._on_send)


    def __str__(self):
        return '<AsyncRPCClient {0} for {1}>'.format(
            self.name or id(self), str(self.channel))


    def call(self, request_msg_parts, callback):
        """Call an RPC service by sending a multipart message request.

        callback(response_msg_parts, None) will be called when
        the response is received, providing the multipart message.

        callback(None, error) will be called if an exception
        occurs when sending.

        If a call is already in progress, this call will be queued up
        and executed once the preceding calls have completed.

        """

        # Do everything via the ioloop to avoid any threading issues
        self.io_loop.add_callback(lambda: self._queue_call(request_msg_parts, callback))


    def close(self, linger = None):
        """Close the channel.
        """
        self.io_loop.add_callback(lambda: self._do_close(linger))

    def _do_close(self, linger):
        if self._stream:
            self._stream.close(linger = linger)
            self._stream = None

    def _queue_call(self, msg, callback):
        self._queue.append((msg, callback))

        # Kick off sending immediately if nothing is in progress
        if len(self._queue) == 1:
            self._send()

    def _send(self):
        if not self._queue:
            return

        request_msg_parts, callback = self._queue[0]
        # Send, continuing when message has been passed to the socket
        self._stream.send_multipart(request_msg_parts)

    def _on_send(self, msg, status):
        request_msg_parts, callback = self._queue[0]
        if status:
            # error when sending
            self._queue.pop(0)
            callback(None, status)
            self._send()
        else:
            # Wait for receiving the response
            self._stream.on_recv(self._on_recv)

    def _on_recv(self, reply_msg_parts):
        # Done receiving for now
        self._stream.on_recv(None)

        request_msg_parts, callback = self._queue.pop(0)
        callback(reply_msg_parts, None)

        # Kick off the next queued call, if any
        self._send()



