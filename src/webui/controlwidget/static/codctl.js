// codplayer web control widget client
//
// Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.

$(function(){
    var stateSymbols = {
	NO_DISC: '\ue60a',
	WORKING: '\ue606',
	PLAY:    '\u25b6',
	PAUSE:   '\u2016',
	STOP:    '\u25a0'
    };

    var socket = io.connect();
    socket.on('connect', function () {
	socket.on('cod-state', function(data) {
	    // TODO: should probably be paranoid about what we get in data

	    var sign = '';
	    if (data.position < 0) {
		sign = '-';
		data.position = -data.position;
	    }
		
	    var posMin = Math.floor(data.position / 60).toString();
	    var posSec = (data.position % 60).toString();

	    if (posSec.length == 1) {
		posSec = '0' + posSec;
	    }

	    var lengthMin = Math.floor(data.length / 60).toString();
	    var lengthSec = (data.length % 60).toString();

	    if (lengthSec.length == 1) {
		lengthSec = '0' + lengthSec;
	    }
	    
	    var stateSymbol = stateSymbols[data.state.toString()];
	    
	    $('#state').text(stateSymbol || data.state.toString());
	    $('#track').text(data.track.toString());
	    $('#no_tracks').text(data.no_tracks.toString());
	    $('#position').text(sign + posMin + ':' + posSec);
	    $('#length').text(lengthMin + ':' + lengthSec);

	    if (data.ripping === false) {
		$('#ripping-state').text('');
		$('#ripping-percentage').text('');
	    }
	    else {
		$('#ripping-state').text('\ue607');
		$('#ripping-percentage').text(data.ripping.toString() + '%');
	    }

	    document.title = data.track.toString() + '/' + data.no_tracks.toString() + ' ' + data.state.toString();
	});
    });

    $('button.command').on('click', function(event) {
	socket.emit('cod-command', { command: this.id });
    });
});
