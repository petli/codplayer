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

    apt-get install \
    cdrdao eject libasound2-dev \
    python-musicbrainz2 python-daemon python-dev 


Build and install
-----------------

The standard Python distutils are used to build and install codplayer:

    python setup.py build
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
    codadmin init /path/to/new/database/dir


Listing database contents
-------------------------

    codadmin list /path/to/database
