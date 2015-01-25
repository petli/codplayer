codplayer releases
==================

1.1 ????-??-??
--------------

### New features

Discs can be linked as an alias for another disc.  An example usecase
is to play a remastered CD when inserting the original release.


1.0 2014-09-16
--------------

The ripping process has been completely refactored.  The old process
used cdrdao to rip both audio and the full TOC in a single pass.  This
had a bunch of problems:

* cdrdao isn't as good as cdparanoia to handle damaged discs,
  resulting in some skips and crackles on those

* the error-correcting code in cdrdao introduces a lot of errors in
  the subchannel reading that the TOC depends on, so pregaps and
  indices on tracks are generally way off

* it just gets confused by discs with hidden tracks before the first
  proper track

This refactoring solves this, by splitting the ripping process into
two phases: first get the audio with cdparanoia, then an undisturbed
TOC with cdrdao.

All discs in a pre-1.0 database will be reripped with the new process
after deploying codplayer 1.0, but the change is backward compatible
to retain any disc information and edits previously added.  The result
is thus that discs are reripped to a higher quality, without having to
restart with a blank database.

### Incompatible changes

Changes requiring action from the user:

* The configuration in `codplayer.conf` have new mandatory parameters:
  `cdparanoia_command` and `FilePublisherFactory(rip_state_path =
  ...)`

* cdparanoia must be installed on the system


Good to know:

* Discs ripped with the old method that never had any information
  added in the admin GUI (i.e. only had a `.toc`, not a `.cod`) are no
  longer visible in the admin GUI.  They will re-appear when reripped
  with the new process.


Changes affecting codplayer clients:

* Ripping state is no longer part of `state.State`, but handled in a
  separate `state.RipState` object instead.  The ZeroMQ state updater
  emits `rip_state` messages with these objects.

* `Track.number` may now be 0, indicating a "hidden" track before the
  nominal first track.


### Other fixes

General:

* All scripts now have a `--version` option
* The player command `version` returns the currently running daemon verson


Database admin GUI:

* User documentation
* Don't overwrite any existing track settings when fetching
  disc information from Musicbrainz
* More efficient sorting speeds up page load


Web control widget:

* Timeout of 30 seconds after the last client disconnects before
  stopping the state subscriptions


codplayerd:

* Limit rip spead with new (optional) config parameter
  `cdrom_read_speed`

* Fix https://github.com/petli/codplayer/issues/30: handle errors on
  pause/resume in `c_alsa_sink` correctly


0.9.1 2014-07-14
----------------

* Fixes https://github.com/petli/codplayer/issues/28: crashed on
  errors before playing any packet at all, e.g. on missing USB audio
  device.


0.9 2014-07-13
--------------

First fully packaged release.
