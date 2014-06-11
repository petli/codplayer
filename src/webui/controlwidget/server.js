#!/usr/bin/env node

// codplayer web control widget server
//
// Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.

'use strict';

var jf = require('jsonfile');
var express = require('express');
var app = express();
var server = require('http').createServer(app);
var io = require('socket.io').listen(server, { 'log level': 1 });
var zmq = require('zmq');

var numClients = 0;
var currentState = null;
var currentDisc = null;


//
// Command line parsing
//

var configPath;
var config;

if (process.argv.length !== 3) {
    console.error('Usage: %s %s config.json', process.argv[0], process.argv[1]);
    process.exit(1);
}

configPath = process.argv[2];
try {
    config = jf.readFileSync(configPath);
}
catch (err) {
    console.error('error reading ' + configPath + ': ' + err);
    process.exit(1);
}

var checkConfigParam = function(param, type) {
    if (!config[param]) {
        console.error('missing config parameter: %s', param);
        process.exit(1);
    }

    if (typeof config[param] !== type) {
        console.error('expected %s config parameter for %s, got: %j', type, param, config[param]);
        process.exit(1);
    }
};

checkConfigParam('serverPort', 'number');
checkConfigParam('commandEndpoint', 'string');
checkConfigParam('stateEndpoint', 'string');



//
// Web server setup
//

app.use(express.static(__dirname + '/static'));

app.get('/', function(req, res) {
    res.sendfile(__dirname + '/static/codctl.html');
});

server.listen(config.serverPort, function() {
    console.log('Server listening on port ' + config.serverPort);
});


//
// ZeroMQ stuff
//

// Forward function declarations
var sendCommand;
var queueCommand;

var stateSocket;
var commandSocket;
var currentCommand = null;
var commandTimeout = null;
var commandQueue = [];

// Handily, both state updates and command responses can be handled
// with the same function
var onSocketMessage = function(type, value) {
    type = type.toString();
    value = value.toString();

    switch (type) {
    case 'state':
        try {
            currentState = JSON.parse(value);
        }
        catch (e) {
            console.log('invalid state: %j', value);
            return;
        }

        io.sockets.emit('cod-state', currentState);

        // Make sure that our information on the disc is in sync with
        // the state.  We might start getting updates in the middle of
        // playing or just miss the disc updates.

        if (currentState.disc_id) {
            if (!currentDisc || currentState.disc_id !== currentDisc.disc_id) {
                console.log('missing current disc, fetching it: %s', currentState.disc_id);
                currentDisc = null;

                // Queue a source command, unless it is already in progress
                if (currentCommand !== 'source') {
                    queueCommand(['source']);
                }
            }
        }
        else {
            if (currentDisc) {
                console.log('no disc, dropping current disc: %s', currentDisc.disc_id);
                currentDisc = null;
                io.sockets.emit('cod-disc', null);
            }
        }
        break;

    case 'disc':
        try {
            currentDisc = JSON.parse(value);
        }
        catch (e) {
            console.log('invalid disc: %j', value);
            return;
        }

        io.sockets.emit('cod-disc', currentDisc);
        break;

    case 'error':
        console.log('codplayer sent an error: %s', value);
        io.sockets.emit('error', value);
        break;

    case 'ok':
        break;

    default:
        console.log('unexpected message: %j', type);
    }
};


var openStateSocket = function() {
    stateSocket = zmq.socket('sub');

    stateSocket.on('error', function(err) {
        console.log('state socket error: %j', err);
        io.sockets.emit('error', err);
    });

    stateSocket.on('message', onSocketMessage);

    stateSocket.connect(config.stateEndpoint);

    // We don't subscribe until there's a client
};

var openCommandSocket = function() {
    commandSocket = zmq.socket('req');

    commandSocket.on('error', function(err) {
        console.log('command socket error: %j', err);
        io.sockets.emit('error', err);
    });

    commandSocket.on('message', function(type, value) {
        console.log('%s response: %s %s', currentCommand, type, value);

        currentCommand = null;
        clearTimeout(commandTimeout);
        commandTimeout = null;

        // Fire off the next queued command, if any, before the
        // processing of this response may trigger anything itself
        if (commandQueue.length > 0) {
            sendCommand(commandQueue.shift());
        }

        onSocketMessage(type, value);
    });

    // Don't let unsent messages linger when we reopen
    commandSocket.linger = 0;

    commandSocket.connect(config.commandEndpoint);
};

/* Send a command now, dropping anything in progress */
sendCommand = function(cmdargs) {
    var cmd = cmdargs[0];

    if (currentCommand) {
        console.log('unfinished command %s replaced by %s', currentCommand, cmd);
        commandSocket.close();
        openCommandSocket();
    }

    currentCommand = cmd;
    console.log('sending command: %j', cmdargs);
    commandSocket.send(cmdargs);

    // It doesn't make sense waiting a long time for commands to take
    // effect, since this mirrors the UI of a CD player.
    commandTimeout = setTimeout(
        function() {
            console.log('timeout sending command: %s', currentCommand);
            currentCommand = null;
            commandTimeout = null;

            // reopen socket to drop the queued command
            commandSocket.close();
            openCommandSocket();

            if (commandQueue.length > 0) {
                sendCommand(commandQueue.shift());
            }
        },
        5000);
};

/* Queue a command to be run when any command in progress finished */
queueCommand = function(cmdargs) {
    if (currentCommand) {
        commandQueue.push(cmdargs);
    }
    else {
        sendCommand(cmdargs);
    }
};

openStateSocket();
openCommandSocket();

//
// Socket callbacks
//

io.sockets.on('connection', function (socket) {
    numClients++;
    console.log('connection, now ' + numClients + ' clients');

    if (numClients === 1) {
        // Start subscribing to all state updates
        stateSocket.subscribe('');

        // And force a state fetch in case there's nothing coming from the server
        queueCommand(['state']);
        queueCommand(['source']);
    }
    else {
        // Tell new client immediately about current state, which
        // should be ok since there are other clients
        if (currentState) {
            socket.emit('cod-state', currentState);
        }

        if (currentDisc) {
            socket.emit('cod-disc', currentDisc);
        }
        else {
            socket.emit('cod-disc', null);
        }
    }

    socket.on('disconnect', function () {
        numClients--;
        console.log('disconnect, now ' + numClients + ' clients');

        if (numClients === 0) {
            // No need to keep listening
            console.log('unsubscribing to state updates');
            stateSocket.unsubscribe('');

            // Which also means that the state is no longer updated,
            // so don't cache it
            currentState = null;
            currentDisc = null;
        }
    });

    socket.on('cod-command', function (data) {
        var command = data.command.split(' ');
        console.log('got command: %j', command);
        sendCommand(command);
    });
});
