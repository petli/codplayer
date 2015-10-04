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
described in the documentation for the class `codplayer.db.Database`.
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

* `codctl`: command line interface
* Web interface (a simple one is in `controlwidget`)
* `codlircd`: IR remote control input events
* `codlcd`: display state on an LCD and status LED
* Control apps (none implemented yet)


ZeroMQ
------

The control and state update interfaces are all based on ZeroMQ
sockets.  This is used to allow a clear separation of duties between
different components (even if they might sometimes be running in the
same process).

For details on the configuration and message formats, see
`doc/zeromq.md`.


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


Ripping process
===============

If you're generous, the CD format is an elegant solution to the
problem of how to read, process and play a digital stream when you had
to build it all with 74xx chips.  If you're feeling more cranky, it's
an analogue format in digital clothing.

Reading the audio samples isn't that tricky on linux, as cdparanoia
does a very good job of salvaging the intention of the mastering
process into PCM files.  A bigger problem is reading all the
additional information that lurks on the disc: pregap lengths, track
indices, CDTEXT etc.  This "subchannel" data is encoded with a kind of
digital carrier wave and must be extracted bit by bit:
http://en.wikipedia.org/wiki/Compact_disc_subcode

cdrdao can read this into a `.toc` text file.  But if you also let
cdrdao read the audio samples at the same time, the error correcting
it does by rereading sections will screw up the subchannel bits and
you get distorted TOC data.

Confusing things more, there might be "hidden" audio before track 1.
If you rip both audio and TOC with cdrdao, the track offsets written
into the `.toc` are mostly correct, but pretends that everything
before the first track is silence.  If you only read the TOC instead
with cdrdao, the file offsets in the `.toc` ignores the hidden track
and thus doesn't match what cdparanoia ripped.

To handle all this, codplayer uses the following process when told
that a disc has been inserted into the reader:

1. Use libdiscid to read the basic TOC (just track offsets and
   lengths, no pregaps etc).
2. Look up the disc information in the database, creating a basic
   record from the TOC if this is the first time the disc is played
3. Check if the disc audio has already been ripped.  If not, kick off
   a cdparanoia process.
4. Start playing, expecting that cdparanoia will rip faster than
   playback speed (if not the player will pause waiting for more data)
5. Check if the full TOC has been read.  If not, run cdrdao to get a
   `.toc` file.  When done, read the file and merge it with the
   existing disc info keeping the best data from each source.
6. Stop spinning the disc.
7. Disco.


License
=======

Copyright 2013-2015 Peter Liljenberg <peter.liljenberg@gmail.com>

codplayer is licensed under the MIT license, please see the file
LICENSE.


Third-party sources
------------------

jQuery is licensed under the MIT license:
* Copyright (c) 2005, 2013 jQuery Foundation, Inc.

mustache.js is licensed under thep MIT license:
* Copyright (c) 2009 Chris Wanstrath (Ruby)
* Copyright (c) 2010 Jan Lehnardt (JavaScript)

bootstrap.js is licensed under the MIT license:
* Copyright 2011-2015 Twitter, Inc.

The icon font was generated from http://icomoon.io/


