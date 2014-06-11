
Controlling codplayerd over ZeroMQ
==================================

The player daemon can publish state updates and recieve commands over
ZeroMQ sockets.  This is enabled by including the ZMQ factories in
`codplayer.conf`.

Beware that there is currently no access control at all, except who
can reach the sockets over the network.  If you worry about other
people skipping maliciously between tracks when you listen to Paul's
Boutique, tighten up your firewall or don't enable this.

All objects that are sent in the messages are
[serialized as JSON](file-formats.md) in separate frames.


State updates
-------------

Create a `SUB` socket and connect to the address specified in the
`ZMQPublisherFactory` config.  Remember to subscribe to `''` to
receive all events.

### state

Sent every time the state changes, including when the play position
moves a second or the ripping progress a percentage point.

Frame format:

    0: "state"
    1: JSON: state.State

### disc

Sent when a new disc is loaded through the `disc` command.  This is
sent before the related `state` messages, so that clients can more
easily determine if they have connected in the middle of a stream and
need to fetch the disc separately.

Frame format:

    0: "disc"
    1: JSON: model.ExtDisc object or null


Cmmands
-------

Create a `REQ` socket and connect to the address specified in the
`ZMQCommandFactory` config.

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

The `source` command returns the current disc:

    0: "disc"
    1: JSON: model.ExtDisc object or null

If a command doesn't have a return value, the response is simply:

    0: "ok"

Command errors are returned as:

    0: "error"
    1: error message as string
    
