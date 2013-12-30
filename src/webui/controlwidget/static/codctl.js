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

    var formatTime = function(seconds) {
	var sign = '';
	if (seconds < 0) {
	    sign = '-';
	    seconds = -seconds;
	}

	var minPart = Math.floor(seconds / 60).toString();
	var secPart = (seconds % 60).toString();

	if (secPart.length == 1) {
	    secPart = '0' + secPart;
	}

	return sign + minPart + ':' + secPart;	
    };


    var socket = io.connect();
    socket.on('connect', function () {
	socket.on('cod-state', function(data) {
	    // TODO: should probably be paranoid about what we get in data

	    var stateSymbol = stateSymbols[data.state.toString()];
	    
	    $('#state').text(stateSymbol || data.state.toString());
	    $('#track').text(data.track.toString());
	    $('#no_tracks').text(data.no_tracks.toString());
	    $('#position').text(formatTime(data.position));
	    $('#length').text(formatTime(data.length));

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

	socket.on('cod-disc', function(disc) {
	    var template = $('#album-template').html();
	    var album;

	    if (disc && disc.tracks && disc.tracks.length) {
		disc.lengthSeconds = function() {
		    return formatTime(this.length);
		};

		disc.artistIfDifferent = function() {
		    return this.artist === disc.artist ? '' : this.artist;
		};
		
		album = $.mustache(template, disc);
	    }
	    else {
		album = $('<div id="album">No disc info</div>');
	    }

	    $('#album').replaceWith(album);
	});
    });

    $('button.command').on('click', function(event) {
	socket.emit('cod-command', { command: this.id });
    });
});
