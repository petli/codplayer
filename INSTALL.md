Installing codplayer
====================

For further information on hardware and OS setup examples, see
https://github.com/petli/codplayer/wiki

Dependencies
------------

codplayer has been tested with Python 2.7.

The `webui/controlwidget` has been tested with Node.js 0.10.x.

codplayer depends on a number of libraries and utilities.  On a Ubuntu
system this should install them all:

    apt-get install libdiscid0 cdrdao eject libasound2-dev \
        python-dev python-virtualenv python-pip \
        libzmq3 libzmq3-dev

Raspbian has an older version of ZeroMQ:

    apt-get install libdiscid0 cdrdao eject libasound2-dev \
        python-dev python-virtualenv python-pip \
        libzmq1 libzmq-dev


Install released package
------------------------

The latest release of codplayer can be installed with `pip`.  It is
recommended to install it in a virtualenv:

    virtualenv ~/cod
    ~/cod/bin/pip install codplayer

Then continue with the configuration, described below.

Install from source
-------------------

To run directly from source the package and scripts must be deployed
in a virtualenv:

    virtualenv ~/cod
    ~/cod/bin/python setup.py develop

This will link up the installation in the virtualenv with the source
directory, so there's no need to re-install after changes.

To install fully in a virtual env:

    ~/cod/bin/python setup.py install


Configuration
-------------

Run `~/cod/bin/codadmin config` to create default config files in the
current directory (you can also specify a target directory on the
command line).  Edit them to reflect the CD device, database paths
etc.

`codplayerd` and `codrestd` look for their config files in
`sys.prefix/local/etc` by default.  In the virtualenv setup above
would be `~/cod/local/etc`, and in a system-wide install
`/usr/local/etc`.

To have codplayer trigger playing/ripping automatically when inserting
a disc, copy
[`etc/udev/rules.d/99-codplayer.rules`](https://github.com/petli/codplayer/blob/master/etc/udev/rules.d/99-codplayer.rules)
to the corresponding `/etc/udev/rules.d` directory.  Edit the file if
`codctl` isn't installed system-wide to its actual path.

On a RaspberryPi, it seems that it doesn't detect any events unless
someone uses the USB CDROM device.  The script
[`etc/trigger_rpi_cdrom_udev.sh`](https://github.com/petli/codplayer/blob/master/tools/trigger_rpi_cdrom_udev.sh)
can be run until that is resolved.


Database initialisation
-----------------------

    mkdir /path/to/new/database/dir
    ~/cod/bin/codadmin init /path/to/new/database/dir

(Assuming installation in a virtualenv in `~/cod`.


Listing database contents
-------------------------

The database can be inspected with `codadmin`.

    ~/cod/bin/codadmin list /path/to/database

Use `--help` to see all commands.


Running codplayer
-----------------

codplayerd is the main deamon.  It will fork itself, unless started
with the `-d` flag to remain in debug mode.  If the configuration is
not located in `/etc/codplayer.conf` the path must be specified with
`-c`:

    ~/cod/bin/codplayerd -c path/to/codplayer.conf

`codctl` can be used to inspect the state of the daemon and to send it
commands.  To see all the commands:

    ~/cod/bin/codctl --help

`codctl` also reads `/etc/codplayer.conf`, and like `codplayerd`
accepts `-c` to indicate another file.


The database admin interface is started with

    ~/cod/bin/codrestd -c path/to/codrest.conf

It can be accessed on `http://localhost:8303` if running locally
(otherwise substitute the hostname and possibly port number with the
correct location).


Installing the web control widget
=================================

The web control widget is a Node.js server, located in
`controlwidget`.  It can be run on any machine which can connect to
the ZeroMQ sockets of `codplayerd`.

When installed, open `http://localhost:8304/` if running locally
(otherwise substitute the hostname and possibly port number with the
correct location).


Getting Node.js
---------------

Ubuntu 14.04 includes a modern Node.js, so it can be installed with
apt-get:

    apt-get install nodejs npm

A precompiled package for Raspbian is available here:
https://github.com/nathanjohnson320/node_arm


Install released package
------------------------

The latest release of the control widget can be installed with npm.
It is recommended to install it in a dedicated directory, e.g.:

    mkdir ~/cod
    cd ~/cod
    npm install codplayer-control


Configuration
-------------

The default settings in `config.json` match the default ZeroMQ
settings in `codplayer.conf`, but might have to be changed if you are
running on different machines or have changed the ports.  It's best to
do this by copying the file somewhere else and change the settings,
then give the filename to `codplayer-control` on the command line.


Running package installation
----------------------------

Assuming the control widget was installed in `~/cod` and using the
default configuration, it can be run like this:

    nohup ~/cod/node_modules/.bin/codplayer-control >> ~/cod/codctlwidget.log 2>&1 &

The server does not fork (right now), so that's why it is run with
nohup and in the background

If you have changed the configuration, the path to the new config can
be proved on the command line:

    ~/cod/node_modules/.bin/codplayer-control /path/to/config.json


Running from source dir
-----------------------

To just run the server from the source directory, the dependencies
must first be installed:

    cd controlwidget
    npm install

Then run the server with either

    ./server.js [/path/to/config.json]

or
    /path/to/node server.js [/path/to/config.json]
