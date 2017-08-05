# codplayer - Radio stream source
#
# Copyright 2017 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import requests
import mad

from .. import audio
from .. import model
from ..source import *
from ..state import State

class RadioStreamSource(Source):
    """Output audio packets from streamed internet radio.

    This source pretends that each configured station is a track, which
    means that prev/next commands work to switch between them.
    """

    def __init__(self, player, stations, index):
        super(RadioStreamSource, self).__init__()

        self.log = player.log
        self.debug = player.debug

        self._stations = stations
        self._current = stations[index]

    def initial_state(self, state):
        return State(state,
                     source = 'radio:{}:{}'.format(self._current.id, self._current.name),
                     no_tracks = len(self._stations))

    def iter_packets(self, track_number, packet_rate):
        self._current = self._stations[track_number]
        self.log('streaming from {}', self._current.url)

        # TODO: really need to do this in the background to be able
        # to give control to source thread periodically

        try:
            mf = self._open_stream(self._current.url)

            self.debug('stream rate: {} Hz, layer: {}, bitrate: {}', mf.samplerate(), mf.layer(), mf.bitrate())
            format = model.Format(rate=mf.samplerate())

            while True:
                try:
                    buf = mf.read()
                except RuntimeError as e:
                    raise SourceError('mpeg decoding error: {}'.format(e))

                if buf is None:
                    # TODO: retry here?
                    raise SourceError('stream stopped')

                p = audio.AudioPacket(format)
                p.data = str(buf)
                yield p

        except requests.RequestException as e:
            raise SourceError('stream error: {}'.format(e))

    def _open_stream(self, url):
        r = requests.get(url, stream=True, timeout=10)
        self.debug('response headers: {}', r.headers)

        if r.status_code != 200:
            raise SourceError('stream error: {} {}'.format(r.status_code, r.status_text))

        content_type = r.headers.get('content-type')
        if content_type != 'audio/mpeg':
            raise SourceError('unsupported stream type: {}'.format(content_type))

        try:
            mf = mad.MadFile(r.raw)
        except RuntimeError as e:
            raise SourceError('mpeg decoding error: {}'.format(e))

        return mf

