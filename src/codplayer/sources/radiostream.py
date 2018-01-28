# codplayer - Radio stream source
#
# Copyright 2017-2018 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import sys
import urllib3
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

    def __init__(self, player, stations, index):
        super(RadioStreamSource, self).__init__()

        self.log = player.log
        self.debug = player.debug

        self._player = player
        self._stations = stations
        self._current = stations[index]

        self._http = urllib3.PoolManager()
        self._stream = None
        self._stalled = False

    @property
    def pausable(self):
        return False

    def initial_state(self, state):
        return State(state, source = 'radio:{}:{}'.format(self._current.id, self._current.name))

    def iter_packets(self):
        self.log('streaming from {}', self._current.url)

        while True:
            self._stream = HttpMpegStream(self._player, self._http, self._current.url)
            self._stalled = False

            try:
                for p in self._stream.iter_packets():
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


    def stalled(self):
        self._stalled = True


class HttpMpegStream(object):
    PACKETS_PER_SECOND = 10
    TIMEOUT = urllib3.Timeout(connect=15, read=5)

    def __init__(self, player, http, url):
        self.log = player.log
        self.debug = player.debug
        self._http = http
        self._url = url
        self._response_error = None
        self._format = None

        try:
            self._response = self._http.request('GET', url,
                                                preload_content=False,
                                                timeout=self.TIMEOUT,
                                                retries=False,
                                                redirect=2)
        except urllib3.exceptions.HTTPError as e:
            raise SourceError('stream error: {}'.format(e))

        self.debug('response headers: {}', self._response.headers)

        if self._response.status != 200:
            raise SourceError('stream error: HTTP response code {}'.format(self._response.status))

        content_type = self._response.headers.get('content-type')
        if content_type != 'audio/mpeg':
            raise SourceError('unsupported stream type: {}'.format(content_type))

    @property
    def format(self):
        return self._format

    def iter_packets(self):
        try:
            mf = mad.MadFile(self)
        except RuntimeError as e:
            raise SourceError('mpeg decoding error: {}'.format(e))

        if self._response_error:
            raise SourceError('http streaming error: {}'.format(self._response_error))

        self.debug('stream rate: {} Hz, layer: {}, bitrate: {}', mf.samplerate(), mf.layer(), mf.bitrate())
        self._format = model.Format(rate=mf.samplerate(), big_endian=(sys.byteorder != 'little'))

        packet_size = (self._format.channels * self._format.bytes_per_sample
                       * self._format.rate) / self.PACKETS_PER_SECOND

        while True:
            data = ''
            while len(data) < packet_size:
                assert self._response is not None

                try:
                    d = mf.read()
                except RuntimeError as e:
                    raise StreamError('mpeg decoding error: {}'.format(e))

                if self._response_error:
                    raise StreamError('http streaming error: {}'.format(self._response_error))

                if d is None:
                    # Timeout, return whatever we've got so far
                    break

                data += str(d)

            if data:
                p = audio.AudioPacket(self._format)
                p.data = data
                yield p
            else:
                # Just give transport control
                yield None


    def close(self):
        if self._response:
            self._response.release_conn()
            self._response = None


    def read(self, length):
        """MadFile doesn't necessarily pass through exceptions correct,
        so handle them locally and just pass on EOF instead.
        """
        try:
            d = self._response.read(length, cache_content=False)
            if not d:
                self._response_error = 'stream closed by server'
            return d

        except urllib3.exceptions.TimeoutError:
            return ''

        except Exception as e:
            self._response_error = e
            return ''

