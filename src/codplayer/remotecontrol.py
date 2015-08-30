# codplayer - Remote control logic
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import time
from . import zerohub

class RemoteControl(object):
    """Listens for button.press.X events and sends
    commands to codplayer.
    """

    # Button names to codplayer commands
    COMMAND_MAPPING = (
        ('PLAY', 'play'),
        ('PAUSE', 'pause'),
        ('PREVIOUS', 'prev'),
        ('NEXT', 'next'),
        ('STOP', 'stop'),
        ('EJECT', 'eject'),
    )

    def __init__(self, daemon, mq_cfg, io_loop):
        self.debug = daemon.debug
        self.log = daemon.log
        self._io_loop = io_loop

        callbacks = {}

        for button, cmd in self.COMMAND_MAPPING:
            callbacks['button.press.' + button] = self._get_button_handler(cmd)

        button_receiver = zerohub.Receiver(
            mq_cfg.input, name = 'remotecontrol', io_loop = self._io_loop,
            callbacks = callbacks)
        self.debug('remotecontrol: receiving button presses on {}', button_receiver)

        self._cmd_sender = zerohub.AsyncSender(
            channel = mq_cfg.player_commands, name = 'remotecontrol',
            io_loop = self._io_loop)
        self.debug('remotecontrol: sending commands to {}', self._cmd_sender)


    def _get_button_handler(self, cmd):
        def handle(receiver, msg):
            now = time.time()
            try:
                ts = float(msg[1])
            except (IndexError, ValueError):
                self.log('error: no timestamp in button message: {}', msg)
                ts = now

            if ts > now or (now - ts) < 0.5:
                # Accept button press as recent enough
                self.debug('sending {} on {}', cmd, msg)
                self._cmd_sender.send_multipart([cmd])
            else:
                self.log('warning: ignoring {}s old message', now - ts)

        return handle
