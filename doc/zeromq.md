
Controlling codplayerd over ZeroMQ
==================================

The player daemon publish state updates and recieve commands over
ZeroMQ sockets. The socket endpoints are defined in the `codmq.conf`
file.

Beware that there is currently no access control at all in the ZeroMQ
sockets themselves.  If you worry about other people skipping
maliciously between tracks when you listen to Paul's Boutique, tighten
up your firewall rules or set the sockets to listen on localhost only
(which is the default).


Data structures
===============

The data structures are JSON serializations of Python objects, with
some special handling to handle enums.  This is provided by the
`codplayer.serialize` module.

state.State
-----------

Example structure:

```json
{
  "disc_id": "IAFL61gCjwAGpOwBz3kjG7QWMa8-",
  "source_disc_id": null,
  "error": null,
  "index": 1,
  "no_tracks": 4,
  "position": 27,
  "state": "PLAY",
  "track": 1
}
```

Properties:

* `state`: One of the state identifiers:
  * `OFF`:     The player isn't running
  * `NO_DISC`: No disc is loaded in the player
  * `WORKING`: Disc has been loaded, waiting for streaming to start
  * `PLAY`:    Playing disc normally
  * `PAUSE`:   Disc is currently paused
  * `STOP`:    Playing finished, but disc is still loaded

* `disc_id`: The Musicbrainz disc ID of the currently loaded disc,
  or `null` if no disc is loaded.

* `source_disc_id`: The source disc ID that triggered the current
  play, which may be different from disc_id (e.g. for aliased discs).
  Set to `null` if the disc isn't linked to another one.

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


state.RipState
--------------

Current state of any ongoing disc ripping process.

Example structure

```json
{
  "disc_id": "6lMdIBppbilQ1I6.oe.8nJSiJc8-",
  "error": null,
  "progress": 34,
  "state": "AUDIO"
}
```

Properties:

* `state`: One of the following identifiers:
  * `INACTIVE`:  No ripping is currently taking place
  * `AUDIO`:     Audio data is being read
  * `TOC`:       TOC is being read

* `disc_id`: The Musicbrainz disc ID of the currently ripped disc, or None

* `progress`: Percentage of 0-100 for current phase, or None if not
known or not applicable

* `error`: The last ripping error, if any.


Events
======

Events are published on the Topic channels defined in `codmq.conf`.
Create a `codplayer.zerohub.Receiver` on the relevant channel to
receive events.

If using ZeroMQ directly, create a `SUB` socket and connect to the
addresses defined by the Topic.  Remember to subscribe to `''` (or
more specific event prefixes) to receive any events.

Topic: state
------------

This topic publishes state updates from different parts of the system.

### state

Sent every time the player state changes, including when the play
position moves a second.

Frame format:

    0: "state"
    1: JSON: state.State

### rip_state

Sent every time the rip state changes, including when the ripping
progress moves a percentage point.

Frame format:

    0: "rip_state"
    1: JSON: state.RipState

### disc

Sent when a new disc is loaded through the `disc` command.  This is
sent before the related `codplayer.state` event, so that clients can more
easily determine if they have connected in the middle of a stream and
need to fetch the disc separately.

Frame format:

    0: "disc"
    1: JSON: model.ExtDisc object or null


Topic: input
------------

This topic publishes input events, e.g. IR remote control button
presses.

### button.press.KEY

Sent by codlircd when a remote control button is pressed.  `KEY` is
the name of the button.  Example event name: `button.press.PLAY`.

Frame format:

    0: "button.press.KEY"
    1: float: time.time() of the button press


### button.repeat.KEY

Sent by codlircd when a remote control button is held down to generate
repeat button events.  `KEY` is the name of the button.

Frame format:

    0: "button.press.KEY"
    1: float: time.time() of the button press
    2: int: repeat count, from 1 and up


Commands
========

codplayer accepts commands on either an RPC channel or a command queue
channel, defined in `codmq.conf` as `player_rpc` and
`player_commands`, respectively.

Send commands to them by creating a `codplayer.zerohub.AsyncRPCClient`
for `player_rpc`, or a `codplayer.zerohub.AsyncSender` instance for
`player_commands`.

If using ZeroMQ directly, create a `REQ` socket connecting to the
address specified for `player_rpc`, or a `PUSH` socket connecting to
the address for `player_commands`.

The command message format are the same, but only `player_rpc` return
a response.

Message Format
--------------

### Request

Each command is split into the command itself and any arguments, each
sent as separate frames:

    0: command
    1: argument 1, if any
    2: argument 2, if any
    ...

### Response

Most commands return the resulting state, if successful:

    0: "state"
    1: JSON: state.State

The `rip_state` command returns the current rip state:

    0: "rip_state"
    1: JSON: state.RipState

The `source` command returns the current disc:

    0: "disc"
    1: JSON: model.ExtDisc object or null

If a command doesn't have a return value, the response is simply:

    0: "ok"
    1: JSON response (this frame may be omitted if there is no value)

Command errors are returned as:

    0: "error"
    1: error message as string
    

codplayer commands
------------------

Run `codctl --help` to get a list of commands that can be sent to the
daemon.
