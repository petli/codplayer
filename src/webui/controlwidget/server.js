// codplayer web control widget server
//
// Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.


var fs = require('fs');
var jf = require('jsonfile');
var express = require('express');
var app = express();
var server = require('http').createServer(app);
var io = require('socket.io').listen(server, { 'log level': 1 });

//
// Command line parsing
//

var configPath;
var config;

if (process.argv.length != 3) {
    console.error('Usage: ' + process.argv[0] + ' ' + process.argv[1]
		  + ' config.json');
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
	console.error('missing config parameter: ' + param);
	process.exit(1);
    }

    if (typeof config[param] !== type) {
	console.error('expected ' + type + ' config parameter: ' + param);
	process.exit(1);
    }
};

checkConfigParam('serverPort', 'number');
checkConfigParam('stateFile', 'string');
checkConfigParam('discFile', 'string');
checkConfigParam('pidFile', 'string');
checkConfigParam('controlFifo', 'string');


//
// State updating
//

var numClients = 0;
var currentState;
var lastStateTime = 0;
var stateDelayed = false;
var currentDisc = null;

var delayTimeout = function(short, long) {
    var timeout = stateDelayed ? long : short;
    stateDelayed = true;

    return timeout;
};


var sendStateOnce = function() {
    jf.readFile(config.stateFile, function(err, state) {
	if (state) {
	    io.sockets.emit('cod-state', state);
	}
    });
};

var sendDisc = function() {
    jf.readFile(config.discFile, function(err, disc) {
	// Ignore errors, as providing disc info is a nice bonus
	currentDisc = disc;

	if (currentState && currentDisc && currentState.disc_id === currentDisc.disc_id) {
	    io.sockets.emit('cod-disc', currentDisc);
	}
	else {
	    io.sockets.emit('cod-disc', null);
	}
    });
};


var sendState = function() {
    if (numClients < 1) {
	console.log('stopping sending state updates');
	return;
    };

    fs.stat(config.stateFile, function(err, stats) {
	if (err) {
	    setTimeout(sendState, delayTimeout(97, 5007));
	}
	else {
	    if (lastStateTime !== stats.mtime.getTime()) {
		// Read updated file
		jf.readFile(config.stateFile, function(err, state) {
	            var timeout = 1007;

		    if (state) {
			io.sockets.emit('cod-state', state);

			if (state.disc_id) {
			    if (currentDisc === null || state.disc_id !== currentDisc.disc_id) {
				sendDisc();
			    }
			}
			else {
			    currentDisc = null;
			    io.sockets.emit('cod-disc', null);
			}

			lastStateTime = stats.mtime.getTime();
			currentState = state;
			stateDelayed = false;

			// Sleep until a bit after the expected next update of the file
			timeout = lastStateTime + 1097 - Date.now();
			if (timeout < 10 || timeout > 1000) {
			    // In case clocks are out of sync...
			    timeout = 1007;
			}
		    } else {
			timeout = delayTimeout(97, 5007);
		    }
                    
	            setTimeout(sendState, timeout);
		});
	    }
	    else {
		// File hasn't changed
	        setTimeout(sendState, delayTimeout(97, 1007));
	    }
	}
    });
};


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
// Socket callbacks
//

io.sockets.on('connection', function (socket) {
    // Tell new client immediately about current state, if any
    if (currentState) {
	socket.emit('cod-state', currentState);
    }

    if (currentState && currentDisc && currentState.disc_id === currentDisc.disc_id) {
	socket.emit('cod-disc', currentDisc);
    }
    else {
	socket.emit('cod-disc', null);
    }

    numClients++;
    console.log('connection, now ' + numClients + ' clients');
    if (numClients == 1) {
	// Kick off sending updates
	sendState();
    }

    socket.on('disconnect', function () {
	numClients--;
	console.log('disconnect, now ' + numClients + ' clients');
    });

    socket.on('cod-command', function (data) {
	var command = data.command;
	var buffer;
	
	console.log('got command: ' + command);

	buffer = new Buffer(command + '\n');

	// Open r+ to fail if there is no FIFO
	fs.open(config.controlFifo, 'r+', function(err, fd) {
	    if (err) {
		console.error('error opening ' + config.controlFifo + ': ' + err);
	    }
	    else {
		fs.write(fd, buffer, 0, buffer.length, null, function(err, written, buffer) {
		    if (err) {
			console.error('error writing to ' + config.controlFifo + ': ' + err);
		    }
		    else {
			// Get an early state update to the clients
			setTimeout(sendStateOnce(), 100);
		    }

		    fs.close(fd, function(err) { });
		});
	    }
	});
    });
});
