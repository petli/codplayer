codplayer - a complicated disc player
=====================================

This is a music player for old farts who insist on listening to albums
and like staring at a shelf full of discs to select the right music,
but still would like to have all the music on a file server.

Therefore, the main user interface is the CD itself.  Insert a disc
and it will be simultaneously ripped to a file server and played.  The
second time the same disc is inserted, it will be played directly from
the ripped files.

Apart from providing backup of your music, having a soft copy of the
discs allows them to be edited.  Some use cases for this include:

* Add artist, title and track information
* Cut out annoying intros and boring extra tracks
* Shuffle the tracks of compilation albums
* Link multi-disc albums so all the discs are played in sequence


Installation
============

Installation and configuration instructions are provided in
[`INSTALL.md`](https://github.com/petli/codplayer/blob/master/INSTALL.md).


License
=======

Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>

codplayer is licensed under an MIT license, please see the file
LICENSE.


Third-party sources
------------------

jQuery is licensed under an MIT license:
* Copyright (c) 2005, 2013 jQuery Foundation, Inc.

mustache.js is licensed under an MIT license:
* Copyright (c) 2009 Chris Wanstrath (Ruby)
* Copyright (c) 2010 Jan Lehnardt (JavaScript)

The icon font was generated from http://icomoon.io/


Architecture
============

At the heart of codplayer is the disc database and the player daemon.
Supplementing these are various control interfaces and database
administration UIs.

The target system setup is to run the player deamon on a fanless,
diskless small computer hooked up to the hifi in the living room,
which is connected over the LAN to a file server which holds the disc
database.  The web control interface and the the database
administration web GUI can be hosted on the file server.


The disc database
-----------------

Each CD is stored in a directory of its own, with the raw PCM data and
the table of contents stored in files.  The format of the database is
described in the documentation for the class codplayer.db.Database.
The disc database must be accessible in the file system of the player.


The player daemon
-----------------

codplayerd links the CD reader and the sound output device with the
disc database, ripping and playing disc.  It is controlled over ZeroMQ
sockets or via a FIFO in the file system.  The current state is sent
to ZeroMQ subscribers, but can also be read from a local file.


Player interfaces
-----------------

codplayer is intended to support different platforms and control
interfaces.  E.g.:

* codctl - command line interface
* codmousectl - use a wireless USB mouse as remote control
* Web interface (a simple one is in `controlwidget`)
* Control apps (none implemented yet)
* Physical button and LED display interfaces (not implemented either)


Database administration
-----------------------

A web GUI for administering the discs in the database is provided via
the REST API provided by `codrestd`.  Current features:

* Browse discs, show track listings
* Edit disc and track details
* Fetch disc and track details from Musicbrainz
* Play discs in a codplayer deamon (which may be on another computer)

Low-level administration is also possible with `codadmin`, run it with
`--help` to see available commands.

