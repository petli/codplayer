
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
checkConfigParam('pidFile', 'string');
checkConfigParam('controlFifo', 'string');


//
// State updating
//

var numClients = 0;

var sendStateOnce = function() {
    jf.readFile(config.stateFile, function(err, state) {
	if (state) {
	    io.sockets.emit('cod-state', state);
	}
    });
};

var sendState = function() {
    if (numClients < 1) {
	console.log('stopping sending state updates');
	return;
    };

    jf.readFile(config.stateFile, function(err, state) {
	var timeout = state.state === 'NO_DISC' ? 5000 : 1000;
	
	if (state) {
	    io.sockets.emit('cod-state', state);
	    setTimeout(sendState, timeout);
	} else {
	    // we might be reading while the state file is being
	    // swapped. In that case, sleep a tad longer than a second
	    // to try to avoid running synchronised with codplayerd
	    console.log('error reading state file: ' + err);
	    setTimeout(sendState, 1100);
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
