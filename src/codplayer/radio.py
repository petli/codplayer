# codplayer - radio station configuration class and metadata sources
#
# Copyright 2013-2018 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import time
import json
import threading
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

    class Song(object):
        def __init__(self, raw):
            self.start = raw['start']
            self.end = raw['end']
            self.title = raw['title'].capitalize()
            self.artist =  ' '.join((s.capitalize() for s in raw['authors'].split()))
            self.album = raw.get('titreAlbum', '').capitalize()

    def __init__(self, channel=MAIN):
        self._url = self.METADATA_URL.format(channel=channel)
        self._current_request = 0
        self._timeout = None

        # The lock protects the following items
        self._lock = threading.Lock()
        self._song_info = None
        self._album_info = None
        self._song_queue = None

    def start(self, player):
        self._player = player
        self._player.io_loop.add_callback(self._fetch)

    def stop(self):
        self._player.io_loop.add_callback(self._stop_fetching)


    @property
    def song(self):
        with self._lock:
            self._update_info()
            return self._song_info

    @property
    def album(self):
        with self._lock:
            self._update_info()
            return self._album_info


    def _update_info(self):
        now = time.time()
        if not self._song_queue or now <= self._song_queue[0].end:
            return

        while self._song_queue and now > self._song_queue[0].end:
            del self._song_queue[0]

        if not self._song_queue or now < self._song_queue[0].start:
            self._song_info = None
            self._album_info = None
            return

        song = self._song_queue[0]
        self._song_info = SongInfo(title=song.title, artist=song.artist)
        self._album_info = SongInfo(title=song.album, artist=song.artist)


    def _fetch(self):
        self._player.debug('FIP: fetching metadata')

        self._timeout = None

        # Detect delayed responses and ignore them
        self._current_request += 1
        request_id = self._current_request

        def callback(response):
            if not self._player or self._current_request != request_id:
                self._player.debug('FIP: dropping stale response {}', request_id)
            else:
                with self._lock:
                    self._handle_response(response)

        self._player.debug('FIP: sending metadata request {} to {}', request_id, self._url)

        client = AsyncHTTPClient()
        client.fetch(self._url, callback)


    def _stop_fetching(self):
        self._player.debug('FIP: stopping metadata fetch')

        if self._timeout:
            self._player.io_loop.remove_timeout(self._timeout)
            self._timeout = None

        # By also ticking the request count any in-flight request will be considered stale and dropped
        self._current_request += 1

        self._song_info = None
        self._album_info = None


    def _handle_response(self, response):
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

        # FIP provides both current, past and upcoming songs. Cache the current and the
        # upcoming songs, to avoid fetching metadata as often
        try:
            data = json.loads(body)

            songs = [self.Song(raw)
                     for raw in data['steps'].values()
                     if raw.has_key('authors')]

            now = int(time.time())
            self._song_queue = sorted((song for song in songs if song.end >= now),
                                      key=lambda song: song.start)

            if not self._song_queue:
                self._player.log('FIP: no current songs returned in metadata')
                self._reschedule()
                return

            song = self._song_queue[0]
            self._song_info = SongInfo(title=song.title, artist=song.artist)
            self._album_info = SongInfo(title=song.album, artist=song.artist)

            for song in self._song_queue:
                self._player.debug(u'FIP: song from {}s: {}', song.start - now, self._song_info)

            last_song_end = max((song.end for song in self._song_queue))

            # Fetch more info some time before last song ends, or in ten minutes
            self._reschedule(min(last_song_end - 30, now + 600))

        except (TypeError, ValueError, KeyError) as e:
            self._player.log('FIP: error processing body json: {}', e)
            self._player.log('FIP: response: {}', body.encode('utf-8'))
            self._reschedule()


    def _reschedule(self, next_fetch = None):
        now = time.time()

        if not next_fetch:
            # error, retry in a bit
            next_fetch = now + 30

            # And clean out any stale state
            self._song_queue = None
            self._song_info = None
            self._album_info = None

        elif next_fetch < now:
            # don't spam the metadata API if song end times are out of sync
            next_fetch = now + 20

        self._player.debug('FIP: fetching metadata in {}s', int(next_fetch - now))
        self._timeout = self._player.io_loop.add_timeout(next_fetch, self._fetch)

