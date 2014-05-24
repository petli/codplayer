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

codplayer depends on a number of libraries and utilities.  On a
Debian/Raspbian/Ubuntu system this should install them all:

    apt-get install libdiscid0 cdrdao eject libasound2-dev python-dev python-virtualenv


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

Copy `etc/codplayer.conf` to `/etc` and edit it to reflect CD devices
etc.

To have codplayer trigger playing/ripping automatically when inserting
a disc, copy `etc/udev/rules.d/99-codplayer.rules` to the
corresponding `/etc/udev/rules.d` directory (assuming codctl has been
installed by setup.py above).

On a RaspberryPi, it seems that it doesn't detect any events unless
someone uses the USB CDROM device.  The script
`tools/trigger_rpi_cdrom_udev.sh` can be run until that is resolved.


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
`src/webui/controlwidget`.  It must be run on the same machine as
`codplayerd`, to be able to control it.  There are three installation
alternatives, listed below.

When installed, open http://hostname:port/ to access the control
interface.

The server does not fork (right now), so it is a good idea to start it
in the background and redirect all output to a log file.  E.g. with a
global install:

    nohup codctl_widget /path/to/webcontrolwidget.json >>/tmp/codctlwidget.log 2>&1 &


Getting Node.js
---------------

The Ubuntu/Debian Node.js package is ancient, so you should download
and compile a fresh version from http://nodejs.org/

To avoid having to compile it on RaspberryPi, you can get a
precompiled package here instead:
https://github.com/nathanjohnson320/node_arm


Configuration
-------------

Copy `etc/webcontrolwidget.json` to a good place, or keep it where it
is.  Edit it to match the settings in `codplayer.conf`.


Running from source dir
-----------------------

To just run the server from the source directory, the dependencies
must first be installed:

    cd src/webui/controlwidget
    npm install

Then run the server with either

    ./server.js /path/to/webcontrolwidget.json

or
    /path/to/node server.js /path/to/webcontrolwidget.json


Installing in dedicated dir
---------------------------

The server can be installed in a dedicated directory.  E.g.:

    mkdir /opt/codplayer/webcontrolwidget
    cd /opt/codplayer/webcontrolwidget
    npm install /path/to/src/webui/controlwidget

Then run it with

    ./node_modules/.bin/codctl_widget /path/to/webcontrolwidget.json


Installing system-wide
----------------------

The widget and all its dependencies can be installed globally too with
`-g`:

    npm install -g /path/to/src/webui/controlwidget

Then run it with

    codctl_widget /path/to/webcontrolwidget.json
