#!/usr/bin/env python

from setuptools import setup
from setuptools.extension import Extension
from setuptools.command.test import test as TestCommand

setup(
    name = 'codplayer',
    version = '2.0',
    license = 'MIT',
    description = 'Complicated CD player',
    author = 'Peter Liljenberg',
    author_email = 'peter.liljenberg@gmail.com',
    keywords = 'cd cdparanoia cdrdao cdplayer',
    url = 'https://github.com/petli/codplayer',

    scripts = [ 'src/codplayerd',
                'src/codctl',
                'src/codadmin',
                'src/codrestd',
                'src/codlcd',
                'src/codlircd',
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
        'discid >= 1.1',
        'musicbrainzngs >= 0.5',
        'pyzmq',
    ],

    dependency_links = [
        'git+https://github.com/adafruit/Adafruit_Python_CharLCD.git#egg=Adafruit_CharLCD-1.0.0',
    ],

    extras_require = {
        'lcd': [
            'Adafruit_CharLCD >= 1.0.0',
            'RPIO',
            ]
    },

    setup_requires = [
        "setuptools_git",
    ],
)
