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

class Config:
    """Configuration is stored in a python file, loaded by this class.
    """

    DEFAULT_FILE = '/etc/codplayer.conf'

    CONFIG_PARAMS = (
        ('database', str),
        ('user', str),
        ('group', str),
        ('pid_file', str),
        ('log_file', str),
        ('state_file', str),
        ('disc_file', str),
        ('control_fifo', str),
        ('cdrom_device', str),
        ('cdrdao_command', str),
        ('eject_command', str),
        ('audio_device_type', str),
        ('start_without_device', bool),
        ('log_performance', bool),

        # File device options
        ('file_play_speed', int),

        # Alsa device options
        ('alsa_card', str),

        )

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
        
            
