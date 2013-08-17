#!/usr/bin/env python

from distutils.core import setup, Extension

setup(
    name = 'codplayer',
    version = '0.1',
    description = 'Complicated CD player',
    author = 'Peter Liljenberg',
    author_email = 'peter.liljenberg@gmail.com',
    
    scripts = [ 'src/codplayerd',
                'src/codctl',
                'src/codadmin',
                ],

    package_dir = { '': 'src' },
    packages = [ 'codplayer',
                 'codplayer.test',
                 ],
    )
