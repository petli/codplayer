# codplayer - common configuration
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes for loading configuration files.
"""

import types

from . import serialize


class ConfigError(Exception):
    pass

class Config:
    """Configuration is stored in a python file, loaded by this class.
    """

    DEFAULT_FILE = '/etc/codplayer.conf'

    CONFIG_PARAMS = (
        ('database', types.StringType),
        ('log_file', types.StringType),
        ('state_file', types.StringType),
        ('control_fifo', types.StringType),
        ('cdrom_device', types.StringType),
        ('cdrdao_command', types.StringType),
        ('audio_device_type', types.StringType),

        # File device options
        ('file_play_speed', types.IntType),

        # Alsa device options
        ('alsa_card', types.StringType),

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
        
            
