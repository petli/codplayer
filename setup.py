#!/usr/bin/env python

from setuptools import setup
from setuptools.extension import Extension
from setuptools.command.test import test as TestCommand

setup(
    name = 'codplayer',
    version = '1.0',
    license = 'MIT',
    description = 'Complicated CD player',
    author = 'Peter Liljenberg',
    author_email = 'peter.liljenberg@gmail.com',
    keywords = 'cd cdrdao cdplayer',
    url = 'https://github.com/petli/codplayer',

    scripts = [ 'src/codplayerd',
                'src/codctl',
                'src/codadmin',
                'src/codmousectl',
                'src/codrestd',
                ],

    package_dir = { '': 'src' },
    packages = [ 'codplayer',
                 'codplayer.test' ],

    package_data = {
        'codplayer': [
            'data/config/*.conf',
            'data/dbadmin/*.html',
            'data/dbadmin/*.js',
            'data/dbadmin/*.css',
            'data/dbadmin/*.woff',
            'data/dbadmin/*/*.js',
            'data/dbadmin/*/*.css',
        ],

        'codplayer.test': ['data/*.xml'],
    },
    include_package_data = True,

    # codrestd would like to use bottle.static_file, so ensure these are unpacked
    eager_resources = [
        'data/dbadmin'
    ],

    ext_modules = [
        Extension('codplayer.c_alsa_sink',
                  ['src/codplayer/c_alsa_sink.c'],
                  libraries = ['asound'])],


    test_suite = 'codplayer.test',

    # Core player dependencies
    install_requires = [
        'python-daemon',
        'bottle',
        'lockfile',
        'python-musicbrainz2',
        'musicbrainzngs >= 0.5',
        'pyzmq',
    ],

    extras_require = {
    },

    setup_requires = [
        "setuptools_git",
    ],
)
