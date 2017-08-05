Installing codplayer
====================

For further information on hardware and OS setup examples, see
the `doc` directory.

Dependencies
------------

codplayer has been tested with Python 2.7, and will not work with
Python 3. 

codplayer depends on a number of libraries and utilities.  On a Ubuntu
system this should install them all:

    apt-get install libdiscid0 cdrdao cdparanoia eject \
        libasound2-dev python-dev python-virtualenv python-pip \
        libzmq3 libzmq3-dev libmad0 libmad0-dev

If you want to run codlcd, you also need to install this:

    apt-get install python-smbus

To stream mp3 radio the pymad library is used.  Unfortunately it
cannot be installed as a pip dependency, so you have to download it
from here and install it following the package instructions (do this
using the virtualenv python binary set up below):
https://pypi.python.org/pypi/pymad/0.9

Install released package
------------------------

The latest release of codplayer can be installed with `pip`.  It is
recommended to install it in a virtualenv, and ensure pip is updated
before installing codplayer:

    virtualenv ~/cod
    ~/cod/bin/pip install -U pip
    ~/cod/bin/pip install codplayer

The database admin web UI `codrestd` require some additional
dependencies which must be installed explicitly:

    ~/cod/bin/pip install 'codplayer[rest]'

Then continue with the configuration, described below.

If you want to run codlcd, the virtual env needs access to the
python-smbus package installed above, and additional dependencies are
needed.  Set it up like this instead:

    virtualenv --system-site-packages ~/cod
    ~/cod/bin/pip install -U pip
    ~/cod/bin/pip install 'codplayer[lcd]'

There's a problem with RPIO 0.10.1 on RPi model B rev 2 (and probably
more versions) when updating to a Linux v4 kernel which stops it from
identifying the platform and understanding the memory mapping.  A
patch is available in this branch:
https://github.com/petli/RPIO/tree/v0.10.1-petli

Either clone it and install it, or uncomment the line in
`dependency_links` in `setup.py` before running the install command
above.


Install from source
-------------------

To run directly from source the package and scripts must be deployed
in a virtualenv:

    virtualenv ~/cod
    ~/cod/bin/python setup.py develop

This will link up the installation in the virtualenv with the source
directory, so there's no need to re-install after changes.

The REST and LCD dependencies can be installed too by extending the command
line:

    ~/cod/bin/python setup.py develop easy_install 'codplayer[lcd]'
    ~/cod/bin/python setup.py develop easy_install 'codplayer[rest]'

To install fully in a virtual env:

    ~/cod/bin/python setup.py install


Configuration
-------------

Run `~/cod/bin/codadmin config` to create default config files in the
current directory (you can also specify a target directory on the
command line).  Edit them to reflect the CD device, database paths
etc.

The daemons look for their config files in `sys.prefix/local/etc` by
default.  In the virtualenv setup above would be `~/cod/local/etc`,
and in a system-wide install `/usr/local/etc`.


### ZeroMQ configuration

Central to everything is `codmq.conf`.  This files defines the topics
where state updates are published and the queues where `codplayerd`
receives commands.  The default configuration defines all of these to
communicate on 127.0.0.1, which is fine for a single-box deployment.
But if you want to publish state or receive commands to/from other
machines, these must be edited:

* On the machine running `codplayerd`, change the address to 0.0.0.0 to
  publish on all interfaces (or limit it to a specific interface
  address)

* On the other machines, put the address of the `codplayerd` machine
  in the configuration instead.


### udev configuration

To have codplayer trigger playing/ripping automatically when inserting
a disc, copy
[`etc/udev/rules.d/99-codplayer.rules`](https://github.com/petli/codplayer/blob/master/etc/udev/rules.d/99-codplayer.rules)
to the corresponding `/etc/udev/rules.d` directory.

Copy these scripts to `/usr/local/bin` and make sure they are executable:
* [`tools/on_cd_load.sh`](https://github.com/petli/codplayer/blob/master/tools/on_cd_load.sh)
* [`tools/on_cd_eject.sh`](https://github.com/petli/codplayer/blob/master/tools/on_cd_eject.sh)

Edit the files if `codctl` isn't installed in `/usr/local/bin` too.

*Note: systemd-based dists, which includes Raspbian 8 and most modern
dists, require different scripts.  These variants all have a
`-systemd` suffix.*


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
