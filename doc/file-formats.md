codplayer file formats
======================

This document describes the various files used to manage the database
and store the player state.

The configuration file format is described in comments in the default
configuration file in the etc/ directory.


Player state
------------

Default path: `/var/run/codplayer.state`

The player deamon stores the current state in a scoreboard file that
is updated whenever the state changes.  During playback, this means
every second.

The file is updated by writing the new state to a temporary file, and
then replacing the state file with this new file.  This guarantees
that a reader never will see a half-written file, but it also means
that readers might not find the file at all in the small gap between
removing the old file and moving the new one in place.  Readers must
be prepared to handle that error by retrying.


Example file:

```json
{
  "disc_id": "IAFL61gCjwAGpOwBz3kjG7QWMa8-", 
  "index": 1, 
  "no_tracks": 4, 
  "position": 27, 
  "ripping": true, 
  "state": "PLAY", 
  "track": 1
}
```

Attributes:

* `state`: One of the state identifiers:
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

* `ripping`: `true` if disc is being ripped while playing, `false` if
   it is played from a previously ripped copy.

