Installing codplayer
====================

This is yet to be packaged up in a general way, but the instructions
here should provide some guidance at least.

The author deploys codplayer on a RaspberryPi B running the
volumio.org dist, but with its PHP web UI disabled since it (among
other things) shuts down udev.


Dependencies
------------

codplayer has been tested with Python 2.7.

The `webui/controlwidget` has been tested with Node.js 0.10.23.

codplayer depends on a number of libraries and utilities.  On a Ubuntu
system this should install them all:

    apt-get install libdiscid0 cdrdao eject libasound2-dev \
        python-dev python-virtualenv \
        libzmq3 libzmq3-dev

Raspbian has an older version of ZeroMQ:

    apt-get install libdiscid0 cdrdao eject libasound2-dev \
        python-dev python-virtualenv \
        libzmq1 libzmq-dev


Build and install
-----------------

The standard Python setuptools are used to install all dependencies
and build the C module.

For development it is recommended to install in virtualenv, e.g.:

    virtualenv ~/cod
    ~/cod/bin/python setup.py develop

This will link up the installation in the virtualenv with the source
directory, so there's no need to re-install after changes.

To install fully in a virtual env:

    ~/cod/bin/python setup.py install

To do a system-wide installation:

    python setup.py install


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


Installing the web control widget
=================================

The web control widget is a Node.js server, located in
`controlwidget`.  It can be run on any machine which can connect to
the ZeroMQ sockets of `codplayerd`.  There are three installation
alternatives, listed below.

When installed, open `http://hostname:port/` to access the control
interface.

The server does not fork (right now), so it is a good idea to start it
in the background and redirect all output to a log file.  E.g. with a
global install:

    nohup codplayer-control >>/tmp/codctlwidget.log 2>&1 &


Getting Node.js
---------------

Ubuntu 14.04 includes a modern Node.js, so it can be installed with
apt-get:

    apt-get install nodejs npm

A precompiled package for Raspbian is available here:
https://github.com/nathanjohnson320/node_arm


Configuration
-------------

The default settings in `controlwidget/config.json` match the default
ZeroMQ settings in `codplayer.conf`, but might have to be changed if
you are running on different machines or have changed the ports.  It's
best to do this by copying the file somewhere else and change the
settings, then give the filename to `codplayer-control` on the command
line.


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


Installing in dedicated dir
---------------------------

The server can be installed in a dedicated directory.  E.g.:

    mkdir /opt/codplayer/controlwidget
    cd /opt/codplayer/controlwidget
    npm install /path/to/controlwidget

Then run it with

    ./node_modules/.bin/codplayer-control [/path/to/config.json]


Installing system-wide
----------------------

The widget and all its dependencies can be installed globally too with
`-g`:

    npm install -g /path/to/controlwidget

Then run it with

    codplayer-control [/path/to/config.json]
