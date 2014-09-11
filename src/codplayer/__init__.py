# codplayer supporting package
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

# Don't include the audio device modules in the list of modules,
# as they may not be available on all systems

from pkg_resources import get_distribution
import os
import time

version = get_distribution('codplayer').version

# Check what file we are loaded from
try:
    date = time.ctime(os.stat(__file__).st_mtime)
except OSError as e:
    date = 'unknown ({})'.format(e)

def full_version():
    return 'codplayer {0} (installed {1})'.format(version, date)


__all__ = [
    'audio',
    'command',
    'config',
    'db',
    'model',
    'player',
    'rest',
    'rip',
    'serialize',
    'sink',
    'source',
    'state',
    'toc',
    'version'
    ]

