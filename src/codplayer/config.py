# codplayer - common configuration
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes for loading configuration files.
"""

from . import serialize


class ConfigError(Exception):
    pass

class Config(object):
    """Configuration is stored in a python file, loaded by this class.
    """

    def __init__(self, config_file = None):
        """Load configuration from config_file, or from the default
        configuration if not provided.
        """

        if config_file is None:
            config_file = self.DEFAULT_FILE

        # Loading config as a python file is convenient, but possibly
        # unsafe.  Let's not worry too much though, as whoever runs
        # this is also likely to have control of the config file
        # contents.
            
        try:
            params = {}
            execfile(config_file, params)
        except SyntaxError, e:
            raise ConfigError('error reading config file {0}: {1}'
                              .format(config_file, e))

        try:
            serialize.populate_object(params, self, self.CONFIG_PARAMS)
        except serialize.LoadError, e:
            raise ConfigError('error reading config file {0}: {1}'
                              .format(config_file, e))
        
            
class PlayerConfig(Config):
    DEFAULT_FILE = '/etc/codplayer.conf'

    CONFIG_PARAMS = (
        serialize.Attr('database', str),
        serialize.Attr('user', str),
        serialize.Attr('group', str),
        serialize.Attr('pid_file', str),
        serialize.Attr('log_file', str),
        serialize.Attr('state_file', str),
        serialize.Attr('disc_file', str),
        serialize.Attr('control_fifo', str),
        serialize.Attr('cdrom_device', str),
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
    DEFAULT_FILE = '/etc/codrest.conf'

    CONFIG_PARAMS = (
        serialize.Attr('database', str),
        serialize.Attr('host', str),
        serialize.Attr('port', int),
        serialize.Attr('players', list),
        )

