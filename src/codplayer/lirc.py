# codplayer - lircd interface
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import socket
import re
import time

from .codaemon import Daemon, DaemonError
from . import zerohub

KEY_LINE_RE = re.compile(r'^[0-9a-fA-F]+ ([0-9a-fA-F]+) KEY_([^ ]+) ')


class LircError(DaemonError): pass

class LircPublisher(Daemon):
    """Read IR button events from the lircd socket and republish them as
    ZeroMQ messages on the input topic.

    This reads from the lircd socket directly, rather than using the
    lirc libs, since we want to pass through every button press or
    repeat as ZeroMQ messages.  This also removes one more packet
    dependency.
    """

    def __init__(self, cfg, mq_cfg, debug = False):
        self._cfg = cfg
        self._mq_cfg = mq_cfg

        self._lirc_data = ''

        # Kick off deamon
        super(LircPublisher, self).__init__(cfg, debug = debug)


    def setup_prefork(self):
        self.log('connecting to lircd on {}', self._cfg.lircd_socket)
        try:
            self._lirc_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, 0)
            self._lirc_socket.connect(self._cfg.lircd_socket)
        except socket.error, e:
            raise LircError('error connecting to lircd socket {}: {}'.format(self._cfg.lircd_socket, e))

        self.log('connected to lircd')

        self.preserve_file(self._lirc_socket)


    def setup_postfork(self):
        self._sender = zerohub.AsyncSender(self._mq_cfg.input, 'lirc', io_loop = self.io_loop)
        self.log('publishing button events on {}', self._sender)


    def run(self):
        # Set up event handler for the lirc socket
        self._lirc_socket.setblocking(False)
        self.io_loop.add_handler(self._lirc_socket.fileno(), self._on_lirc_data, self.io_loop.READ)

        # Let io loop take care of the rest
        self.io_loop.start()


    def _on_lirc_data(self, fd, event):
        if event & self.io_loop.READ:
            now = time.time()
            data = self._lirc_socket.recv(1024)
            if not data:
                self.log('lircd socket unexpectedly closed, shutting down daemon')
                self.io_loop.stop()

            self._lirc_data += data
            lines = self._lirc_data.split('\n')

            # Last item is incomplete line, save it for next iteration
            self._lirc_data = lines.pop()

            for line in lines:
                m = KEY_LINE_RE.match(line)
                if not m:
                    self.log('unexpected lircd socket data: {}', line)
                else:
                    repeat = int(m.group(1), 16)
                    button = m.group(2)

                    if repeat == 0:
                        msg = ['button.press.' + button, str(now)]
                    else:
                        msg = ['button.repeat.' + button, str(now), str(repeat)]

                    self.debug('sending: {}', msg)
                    self._sender.send_multipart(msg)
