# codplayer - radio station configuration class and metadata sources
#
# Copyright 2013-2018 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import time
import json
from tornado.httpclient import AsyncHTTPClient

from .state import SongInfo, AlbumInfo


class Station(object):
    """Radio station configuration:

    id: station id, used to select which station to play
    url: mp3 stream URL
    name: human-readable station name
    """

    def __init__(self, id, url, name, metadata = None):
        self.id = id
        self.url = url
        self.name = name
        self.metadata = metadata


class Metadata(object):
    """Interface for radio stream metadata providers."""

    def start(self, player):
        """Start fetching and updating metadata."""
        raise NotImplementedError()

    def stop(self):
        """Stop metadata updates."""
        raise NotImplementedError()

    @property
    def song(self):
        """Current SongInfo, or None if not known."""
        raise NotImplementedError()

    @property
    def album(self):
        """Current AlbumInfo, or None if not known."""
        raise NotImplementedError()


class FIPMetadata(Metadata):
    """Fetch song metadata for Radio FIP."""

    # TODO: list add other channels here
    MAIN = 7

    METADATA_URL = 'https://www.fip.fr/livemeta/{channel}'

    def __init__(self, channel=MAIN):
        self._url = self.METADATA_URL.format(channel=channel)
        self._current_request = 0
        self._song_info = None
        self._album_info = None

    def start(self, player):
        self._player = player
        self._player.io_loop.add_callback(self._fetch)

    def stop(self):
        self._player = None
        self._song_info = None
        self._album_info = None

    @property
    def song(self):
        return self._song_info

    @property
    def album(self):
        return self._album_info


    def _fetch(self):
        # Detect delayed responses and ignore them
        self._current_request += 1
        request_id = self._current_request

        def callback(response):
            if not self._player or self._current_request != request_id:
                self._player.debug('FIP: dropping stale response {}', request_id)
            else:
                self._handle_response(response)

        self._player.debug('FIP: sending metadata request {} to {}', request_id, self._url)

        client = AsyncHTTPClient()
        client.fetch(self._url, callback)


    def _handle_response(self, response):
        def capitalize(name):
            return ' '.join((s.capitalize() for s in name.split()))

        if response.error:
            self._player.log('FIP: metadata request failed: {}', response.error)
            self._reschedule()
            return

        if response.code != 200:
            self._player.log('FIP: metadata response not OK: {} {}', response.code, response.reason)
            self._reschedule()
            return

        content_type = response.headers.get('Content-Type')
        if content_type != 'application/json':
            self._player.log('FIP: unexpected metadata response content type: {}', content_type)
            self._reschedule()
            return

        try:
            body = response.body.decode('utf-8')
        except UnicodeDecodeError as e:
            self._player.log('FIP: error decoding body as UTF-8: {}', e)
            self._reschedule()
            return

        # Quick and dirty extraction of song info from JSON data.
        # FIP provides info about upcoming songs, so that could be
        # cached here to reduce HTTP requests and provide quicker updates.
        try:
            data = json.loads(body)

            levels = data['levels']
            position = levels[0]['position']
            items = levels[0]['items']

            current_id = items[position]

            steps = data['steps']
            song = steps[current_id]

            artist = capitalize(song['authors'])
            song_info = SongInfo(title=capitalize(song['title']), artist=artist)
            album_info = SongInfo(title=capitalize(song['titreAlbum']), artist=artist)

            song_end = song['end'] + 1

            self._player.debug('FIP: playing song {}, album {}, next in {}s',
                               song_info, album_info, int(song_end - time.time()))

            self._song_info = song_info
            self._album_info = album_info
            self._reschedule(song_end)

        except (TypeError, ValueError, KeyError) as e:
            self._player.log('FIP: error processing body json: {}', e)
            self._player.log('FIP: response: {}', body.encode('utf-8'))
            self._reschedule()


    def _reschedule(self, next_fetch = None):
        if not next_fetch:
            # error, retry in a bit
            next_fetch = time.time() + 30

            # And clean out any stale state
            self._song_info = None
            self._album_info = None

        elif next_fetch < time.time():
            # don't spam the metadata API if song end times are out of sync
            next_fetch = time.time() + 5

        self._player.io_loop.add_timeout(next_fetch, self._fetch)

