$(function(){
    var socket = io.connect();
    socket.on('connect', function () {
	socket.on('cod-state', function(data) {
	    // TODO: should probably be paranoid about what we get in data

	    var sign = '';
	    if (data.position < 0) {
		sign = '-';
		data.position = -data.position;
	    }
		
	    var posMin = (data.position / 60).toFixed(0);
	    var posSec = (data.position % 60).toFixed(0);

	    if (posSec.length == 1) {
		posSec = '0' + posSec;
	    }
	    
	    $('#state').text(data.state.toString());
	    $('#track').text(data.track.toString());
	    $('#no_tracks').text(data.no_tracks.toString());
	    $('#position').text(posMin + ':' + posSec);
	    $('#ripping').text(data.ripping ? '(ripping)' : '');
	});
    });

    $('button.command').on('click', function(event) {
	socket.emit('cod-command', { command: this.id });
    });
});
