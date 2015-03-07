// codplayer web control widget client
//
// Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.

$(function(){
    'use strict';

    var stateSymbols = {
        NO_DISC: '\ue60a',
        WORKING: '\ue606',
        PLAY:    '\u25b6',
        PAUSE:   '\u2016',
        STOP:    '\u25a0'
    };

    var titleStateSymbols = {
        NO_DISC: '',
        WORKING: '...',
        PLAY:    '\u25b6',
        PAUSE:   '\u2016',
        STOP:    '\u25a0'
    };

    var highlightedTrack = null;
    var showingRipping = false;
    var sourceDiscId = null;

    var formatTime = function(seconds) {
        var sign = '';
        if (seconds < 0) {
            sign = '-';
            seconds = -seconds;
        }

        var minPart = Math.floor(seconds / 60).toString();
        var secPart = (seconds % 60).toString();

        if (secPart.length === 1) {
            secPart = '0' + secPart;
        }

        return sign + minPart + ':' + secPart;
    };

    var highlightTrack = function() {
        if (highlightedTrack !== null) {
            var el = $('#track-' + highlightedTrack);

            if (el.size()) {
                el.addClass('current-track');
                el.get(0).scrollIntoView(true);
            }
        }
    };

    var currentErrors = {};
    var setError = function(error, type) {
        if (error === currentErrors[type]) {
            return;
        }

        console.log('%s error: %s', type, error);

        var $errorBox = $('#' + type + '-error');

        currentErrors[type] = error;

        if (error) {
            $errorBox.text(error);
            $errorBox.fadeIn({
                duration: 200,
                queue: false,
            });
        }
        else {
            $errorBox.fadeOut({
                duration: 500,
                queue: true,
            });
        }
    };

    var socket = io.connect();
    socket.on('connect', function () {
        socket.on('cod-state', function(data) {
            // Any message from server clears its errors
            setError(null, 'server');

            // TODO: should probably be paranoid about what we get in data

            var state = data.state.toString();
            var stateSymbol = stateSymbols[state] || state;
            var titleState = titleStateSymbols[state] || state;
            var position = formatTime(data.position);
            var length = formatTime(data.length);
            var title = '';

            $('#state').text(stateSymbol);
            $('#track').text(data.track.toString());
            $('#no_tracks').text(data.no_tracks.toString());
            $('#position').text(position);
            $('#length').text(length);

            if (state !== 'NO_DISC') {
                title = (titleState + ' ' +
                         data.track.toString() + '/' + data.no_tracks.toString() + ' ' +
                         position + '/' + length);
            }

            document.title = title || 'codplayer';
            data.summary = title;

            // Show "play source" button if different from actually played disc
            if (sourceDiscId !== data.source_disc_id) {
                sourceDiscId = data.source_disc_id;
                if (sourceDiscId) {
                    $('#play-source').show();
                }
                else {
                    $('#play-source').hide();
                }
            }

            // Change current track highlightning, if any
            var ht = (state === 'PLAY' || state === 'PAUSE') ? data.track : null;
            if (highlightedTrack !== ht) {
                highlightedTrack = ht;
                $('.current-track').removeClass('current-track');
                highlightTrack();
            }

            // If we're embedded in an iframe, send the state update to the parent too
            if (window.parent !== window) {
                window.parent.postMessage(
                    JSON.stringify({
                        codplayer: {
                            state: data,
                        }
                    }), "*");
            }

            // Update the error display, if any
            setError(data.error, 'state');
        });

        socket.on('cod-rip-state', function(data) {
            setError(null, 'server');

            switch (data.state)
            {
            case null:
            case undefined:
            case 'INACTIVE':
                if (showingRipping) {
                    $('#ripping-state').fadeOut();
                    showingRipping = false;
                }
                break;


            default:
                if (typeof data.progress === 'number') {
                    $('#ripping-percentage').text(data.progress.toString() + '%');
                }
                else {
                    $('#ripping-percentage').text(data.state);
                }

                if (!showingRipping) {
                    $('#ripping-state').fadeIn();
                    showingRipping = true;
                }
                break;
            }

            // Update the error display, if any
            setError(data.error, 'rip');
        });

        socket.on('cod-disc', function(disc) {
            setError(null, 'server');

            var template = $('#album-template').html();
            var album;

            if (disc && disc.tracks && disc.tracks.length) {
                disc.trackHasTitle = function() {
                    return this.title && this.title.length > 0;
                };

                disc.lengthTime = function() {
                    return formatTime(this.length);
                };

                disc.artistIfDifferent = function() {
                    return this.artist === disc.artist ? '' : this.artist;
                };

                album = $.mustache(template, disc);
            }
            else {
                album = $('<div id="album"></div>');
            }

            $('#album').replaceWith(album);
            highlightTrack();
        });
    });

    socket.on('cod-error', function(error) {
        setError(error, 'server');
    });

    $('button.command').on('click', function(event) {
        if (this.id === 'play-source') {
            socket.emit('cod-command', { command: 'disc ' + sourceDiscId });
        }
        else {
            socket.emit('cod-command', { command: this.id });
        }
    });

    /* Accept messages from a containing window to play a disc */
    $(window).on('message', function(event) {
        var ev = event.originalEvent;
        var data = JSON.parse(ev.data);
        var cmd;

        if (ev.source === window.parent && data && data.codplayer) {
            if (data.codplayer.play && typeof data.codplayer.play.disc === 'string') {
                cmd = 'disc ' + data.codplayer.play.disc;
                console.log('Got message from parent, issuing command: %s', cmd);
                socket.emit('cod-command', { command: cmd });
            }
            else {
                console.error('malformed codplayer message: %j', data);
            }
        }
        else {
            console.warning('unexpected message from %j: %j', ev.source, data);
        }
    });
});
