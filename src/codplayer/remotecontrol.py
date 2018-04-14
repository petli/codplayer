# codplayer - Remote control logic
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import time
from . import codaemon
from . import zerohub

class RemoteControl(codaemon.Plugin):
    """Listens for button.press.X events and sends
    commands to codplayer.
    """

    # Button names to codplayer commands
    COMMAND_MAPPING = {
        'PLAY': 'play',
        'PAUSE': 'pause',
        'PREVIOUS': 'prev',
        'NEXT': 'next',
        'STOP': 'stop',
        'EJECT': 'eject',
    }

    def __init__(self, **custom_commands):
        self._commands = dict(self.COMMAND_MAPPING)
        self._commands.update(custom_commands)

    def setup_prefork(self, player, cfg, mq_cfg):
        self._player = player
        self._mq_cfg = mq_cfg
        self.debug = player.debug
        self.log = player.log

    def setup_postfork(self):
        callbacks = {}

        for button, cmd in self._commands.items():
            callbacks['button.press.' + button] = self._get_button_handler(cmd)

        button_receiver = zerohub.Receiver(
            self._mq_cfg.input, name = 'remotecontrol', io_loop = self._player.io_loop,
            callbacks = callbacks)
        self.log('remotecontrol: receiving button presses on {}', button_receiver)

        self._cmd_sender = zerohub.AsyncSender(
            channel = self._mq_cfg.player_commands, name = 'remotecontrol',
            io_loop = self._player.io_loop)
        self.log('remotecontrol: sending commands to {}', self._cmd_sender)


    def _get_button_handler(self, cmd):
        cmdparts = cmd.split(' ')

        def handle(receiver, msg):
            now = time.time()
            try:
                ts = float(msg[1])
            except (IndexError, ValueError):
                self.log('error: no timestamp in button message: {}', msg)
                ts = now

            if ts > now or (now - ts) < 0.5:
                # Accept button press as recent enough
                self.debug('sending {} on {}', cmdparts, msg)
                self._cmd_sender.send_multipart(cmdparts)
            else:
                self.log('warning: ignoring {}s old message', now - ts)

        return handle
