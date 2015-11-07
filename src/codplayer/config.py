# codplayer - common configuration
#
# Copyright 2013-2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes for loading configuration files.
"""

import sys
import os

from . import serialize
from . import state
from . import command
from . import zerohub
from . import lcd
from . import codaemon

class ConfigError(Exception):
    pass

class Config(object):
    """Configuration is stored in a python file, loaded by this class.
    """

    def __init__(self, config_file = None):
        """Load configuration from config_file, or from the default
        configuration if not provided.
        """

        self.config_path = config_file or self.DEFAULT_FILE

        # Loading config as a python file is convenient, but possibly
        # unsafe.  Let's not worry too much though, as whoever runs
        # this is also likely to have control of the config file
        # contents.
            
        try:
            params = {}
            execfile(self.config_path, params)
        except (IOError, SyntaxError) as e:
            raise ConfigError('error reading config file {0}: {1}'
                              .format(self.config_path, e))

        try:
            serialize.populate_object(params, self, self.CONFIG_PARAMS)
        except serialize.LoadError, e:
            raise ConfigError('error reading config file {0}: {1}'
                              .format(self.config_path, e))
        

class DaemonConfig(Config):
    DAEMON_PARAMS = (
        serialize.Attr('user', str, optional = True),
        serialize.Attr('group', str, optional = True),
        serialize.Attr('pid_file', str),
        serialize.Attr('log_file', str),
        serialize.Attr('plugins', list_type = codaemon.Plugin, optional = True),
    )

    def __init__(self, config_file = None):
        self.CONFIG_PARAMS += self.DAEMON_PARAMS
        super(DaemonConfig, self).__init__(config_file)


class MQConfig(Config):
    DEFAULT_FILE = os.path.join(sys.prefix, 'local/etc/codmq.conf')

    CONFIG_PARAMS = (
        serialize.Attr('state', zerohub.Topic),
        serialize.Attr('input', zerohub.Topic),
        serialize.Attr('player_rpc', zerohub.RPC),
        serialize.Attr('player_commands', zerohub.Queue),
        )


class PlayerConfig(DaemonConfig):
    DEFAULT_FILE = os.path.join(sys.prefix, 'local/etc/codplayer.conf')

    CONFIG_PARAMS = (
        serialize.Attr('codmq_conf_path', str),
        serialize.Attr('database', str),
        serialize.Attr('cdrom_device', str),
        serialize.Attr('cdrom_read_speed', int, optional = True),
        serialize.Attr('cdparanoia_command', str),
        serialize.Attr('cdrdao_command', str),
        serialize.Attr('eject_command', str),
        serialize.Attr('audio_device_type', str),
        serialize.Attr('start_without_device', bool),
        serialize.Attr('log_performance', bool),

        # File device options
        serialize.Attr('file_play_speed', int),

        # Alsa device options
        serialize.Attr('alsa_card', str),

        )


class RestConfig(Config):
    DEFAULT_FILE = os.path.join(sys.prefix, 'local/etc/codrest.conf')

    CONFIG_PARAMS = (
        serialize.Attr('database', str),
        serialize.Attr('host', str),
        serialize.Attr('port', int),
        serialize.Attr('players', list),
        )


class LCDConfig(DaemonConfig):
    DEFAULT_FILE = os.path.join(sys.prefix, 'local/etc/codlcd.conf')

    CONFIG_PARAMS = (
        serialize.Attr('codmq_conf_path', str),
        serialize.Attr('lcd_factory', lcd.ILCDFactory),
        serialize.Attr('formatter', lcd.ILCDFormatter),
        serialize.Attr('brightness_levels',
                       list_type = lcd.Brightness, optional = True),
        )

class LircConfig(DaemonConfig):
    DEFAULT_FILE = os.path.join(sys.prefix, 'local/etc/codlircd.conf')

    CONFIG_PARAMS = (
        serialize.Attr('codmq_conf_path', str),
        serialize.Attr('lircd_socket', str),
        )
