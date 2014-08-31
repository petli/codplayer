codplayer file formats
======================

This document describes the various files used to manage the database
and store the player state.

The configuration file format is described in comments in the default
configuration file in the `src/codplayer/data/config` directory.

All JSON files are updated by writing the new contents to a temporary
file, and then replacing the target file with this new file.  This
guarantees that a reader never will see a half-written file, but it
also means that readers might not find the file at all in the small
gap between removing the old file and moving the new one in place.
Readers must be prepared to handle that error by retrying.


Player state
------------

Default path: `/var/run/codplayer.state`

The player deamon stores the current state in a scoreboard file that
is updated whenever the state changes.  During playback, this means
every second.


Example file:

```json
{
  "disc_id": "IAFL61gCjwAGpOwBz3kjG7QWMa8-", 
  "error": null,
  "index": 1, 
  "no_tracks": 4, 
  "position": 27, 
  "state": "PLAY", 
  "track": 1
}
```

Attributes:

* `state`: One of the state identifiers:
  * `OFF`:     The player isn't running
  * `NO_DISC`: No disc is loaded in the player
  * `WORKING`: Disc has been loaded, waiting for streaming to start
  * `PLAY`:    Playing disc normally
  * `PAUSE`:   Disc is currently paused
  * `STOP`:    Playing finished, but disc is still loaded

* `disc_id`: The Musicbrainz disc ID of the currently loaded disc,
  or `null` if no disc is loaded.

* `track`: Current track number being played, counting from 1. 0 if
  stopped or no disc is loaded.

* `no_tracks`: Number of tracks on the disc to be played. 0 if no disc is loaded.

* `index`: Track index currently being played. 0 for pre_gap, 1 or
  higher for main sections.

* `position`: Current position in track in whole seconds, counting
  from index 1.  This means that in the pregap, the position is
  negative counting down towards 0.

* `length`: Length of the current track in whole seconds, counting
  from index 1 (i.e. not including any pregap).

* `error`: A string giving the error state of the player, if any.


Ripping state
-------------

Default path: `/var/run/codplayer.ripstate`

When a disc is ripped into the database the player deamon stores the
current rip state in a scoreboard file.

Example file:

    {
      "disc_id": "6lMdIBppbilQ1I6.oe.8nJSiJc8-",
      "error": null,
      "progress": 34,
      "state": "AUDIO"
    }

Attributes:

* `state`: One of the following identifiers:
  * `INACTIVE`:  No ripping is currently taking place
  * `AUDIO`:     Audio data is being read
  * `TOC`:       TOC is being read

* `disc_id`: The Musicbrainz disc ID of the currently ripped disc, or None

* `progress`: Percentage of 0-100 for current phase, or None if not
known or not applicable

* `error`: The last ripping error, if any.
