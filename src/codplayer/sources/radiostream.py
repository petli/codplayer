# codplayer - Radio stream source
#
# Copyright 2017-2018 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import sys
import urllib
import httplib
import socket
import select
import time

import mad

from .. import audio
from .. import model
from ..source import *
from ..state import State

class StreamError(Exception):
    """Streaming errors where the source should retry opening"""
    pass


class RadioStreamSource(Source):
    """Output audio packets from streamed internet radio.
    """

    def __init__(self, player, stream):
        super(RadioStreamSource, self).__init__()

        self.log = player.log
        self.debug = player.debug

        self._player = player
        self._stations = player.cfg.radio_stations
        self._current = stream
        self._stream = None
        self._stalled = False

    @property
    def pausable(self):
        return False

    def initial_state(self, state):
        return State(state, stream = self._current.name)

    def iter_packets(self):
        self.log('streaming {} from {}', self._current.name, self._current.url)

        if self._current.metadata:
            self._current.metadata.start(self._player)

        while True:
            self._stream = HttpMpegStream(self._player, self._current.url)
            self._stalled = False

            try:
                for p in self._stream.iter_packets(self._current.metadata):
                    if p is None and self._stalled:
                        raise StreamError('transport stalled')

                    if p is not None:
                        self._stalled = False

                    yield p

            except StreamError, e:
                self.log('stream error, restarting: {}', e)

                if self._stream:
                    # Send out a second of silence to make the break less sharp
                    if self._stream.format:
                        p = audio.AudioPacket(self._stream.format)
                        p.data = '\0' * (self._stream.format.channels * self._stream.format.bytes_per_sample
                                         * self._stream.format.rate)
                        yield p

                    self._stream.close()
                    self._stream = None

    def stopped(self):
        if self._stream:
            self._stream.close()
            self._stream = None

        if self._current.metadata:
            self._current.metadata.stop()


    def stalled(self):
        self._stalled = True


    def next_source(self, state):
        if len(self._stations) < 2:
            return self

        index = self._stations.index(self._current)
        return RadioStreamSource(self._player, self._stations[(index + 1) % len(self._stations)])


    def prev_source(self, state):
        if len(self._stations) < 2:
            return self

        index = self._stations.index(self._current)
        return RadioStreamSource(self._player, self._stations[index - 1])


class HttpMpegStream(object):
    PACKETS_PER_SECOND = 10
    START_STREAMING_TIMEOUT = 15

    def __init__(self, player, url):
        self.log = player.log
        self.debug = player.debug
        self._response_error = None
        self._format = None
        self._mpeg = None
        self._connect(url)

    def _connect(self, url):
        try:
            # TODO: there's no way to control how long to wait here.  It can potentially
            # block forever if the socket connection is established but the server then
            # doesn't respond to the request (unlikely, but not good)
            r = urllib.urlopen(url)
        except (httplib.HTTPException, IOError) as e:
            raise SourceError('stream error: {}'.format(e))

        headers = r.info()
        self.debug('response headers: {}', headers)

        if r.getcode() != 200:
            raise SourceError('stream error: HTTP response code {}'.format(r.getcode()))

        content_type = headers.get('content-type')
        if content_type != 'audio/mpeg':
            raise SourceError('unsupported stream type: {}'.format(content_type))

        transfer_encoding = headers.get('transfer-encoding')
        if transfer_encoding:
            raise SourceError('unsupported transfer encoding: {}'.format(transfer_encoding))

        content_encoding = headers.get('content-encoding')
        if transfer_encoding:
            raise SourceError('unsupported content encoding: {}'.format(content_encoding))

        # Take over the socket to do raw streaming ourselves, so the request object
        # can be closed
        self._socket = socket.fromfd(r.fileno(), socket.AF_INET, socket.SOCK_STREAM)
        r.close()

        self._poll = select.poll()
        self._poll.register(self._socket, select.POLLIN)

        try:
            mf = mad.MadFile(self)
        except RuntimeError as e:
            raise SourceError('mpeg decoding error: {}'.format(e))

        if self._response_error:
            raise SourceError('http streaming error: {}'.format(self._response_error))

        self.debug('stream rate: {} Hz, layer: {}, bitrate: {}', mf.samplerate(), mf.layer(), mf.bitrate())
        self._format = model.Format(rate=mf.samplerate(), big_endian=(sys.byteorder != 'little'))
        self._mpeg = mf

    @property
    def format(self):
        return self._format

    def iter_packets(self, metadata):
        packet_size = (self._format.channels * self._format.bytes_per_sample
                       * self._format.rate) / self.PACKETS_PER_SECOND

        while True:
            data = ''
            while len(data) < packet_size:
                assert self._socket is not None

                try:
                    d = self._mpeg.read()
                except RuntimeError as e:
                    raise StreamError('mpeg decoding error: {}'.format(e))

                if self._response_error:
                    raise StreamError('http streaming error: {}'.format(self._response_error))

                if d is None:
                    # Timeout, return whatever we've got so far
                    break

                data += str(d)

            if data:
                p = StreamAudioPacket(self._format, metadata)
                p.data = data
                yield p
            else:
                # Just give transport control
                yield None


    def close(self):
        self._poll = None
        if self._socket:
            self._socket.close()
            self._socket = None


    def read(self, length):
        """MadFile doesn't necessarily pass through exceptions correct,
        but it passes on EOF fine while allowing us to retry reading
        later.  So handle errors here and treat them as EOF.
        """

        try:
            timeout = time.time() + self.START_STREAMING_TIMEOUT

            data = ''
            while len(data) < length:
                for fd, event in self._poll.poll(1000):
                    if fd == self._socket.fileno() and event & select.POLLIN:
                        d = self._socket.recv(length - len(data))
                        if d:
                            data += d
                        else:
                            self._response_error = 'stream closed by server'

                if self._mpeg is not None:
                    # Once the mpeg file header has been read and we're streaming
                    # samples, just return what we've got, not necessarily all
                    # the data asked for. MadFile will keep retrying.
                    break

                if time.time() > timeout:
                    self._response_error = 'timeout waiting for stream to start'
                    return ''

            return data

        except Exception as e:
            self._response_error = e
            return ''


class StreamAudioPacket(audio.AudioPacket):
    def __init__(self, format, metadata):
        super(StreamAudioPacket, self).__init__(format)
        self._metadata = metadata

    def update_state(self, state):
        if not self._metadata:
            return None

        if state.song_info == self._metadata.song and state.album_info == self._metadata.album:
            # No change
            return None

        return State(state, song_info=self._metadata.song, album_info=self._metadata.album)
