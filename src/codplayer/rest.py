# codplayer - REST API using tornado and sockjs
#
# Copyright 2014-2017 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

from pkg_resources import resource_filename
import os
import sys
import time
import traceback
import json

from tornado import web
from tornado import httpserver
from tornado import netutil
from tornado import ioloop
from sockjs.tornado import SockJSRouter, SockJSConnection
import musicbrainzngs

from . import version
from . import config
from . import command
from . import db
from . import model
from . import serialize
from . import state
from . import zerohub
from .codaemon import Daemon


class RemotePlayer(object):
    """Represents a codplayer instance that can be controlled and subscribed to.

    All state updates are sent as a JSON dictionary on this format.
    'id' is always being present, while the other properties
    are omitted or null if they are unchanged or not known.

    {
        'id': <player ID>,
        'state': { ... },
        'rip_state' { ... },
        'disc': { ... }
    }
    """

    TIMEOUT = 5

    def __init__(self, id, name, mq_config_file):
        self.id = id
        self.name = name
        self._mq_config_file = mq_config_file
        self._cfg = None
        self._daemon = None
        self._socket_router = None
        self._current_state = None
        self._current_rip_state = None
        self._current_disc = None
        self._state_client = None
        self._subscribers = set()

    @property
    def json(self):
        # Very simple serialization...
        return { 'id': self.id, 'name': self.name }


    def load_mq_config(self, config_path):
        self._cfg = config.MQConfig(os.path.join(os.path.dirname(config_path),
                                                 self._mq_config_file))

    def start(self, daemon, socket_router):
        self._daemon = daemon
        self._socket_router = socket_router


    def call(self, cmd, on_response=None, on_error=None):
        assert self._daemon is not None

        def on_call_timeout():
            self._daemon.log('player {}: timeout for cmd {}', self.id, cmd)
            client.close()
            if on_error:
                on_error('timeout')

        def on_call_response(response):
            self._daemon.io_loop.remove_timeout(timeout)
            client.close()
            on_response(response)

        def on_call_error(error):
            self._daemon.log('player {}: error for cmd {}: {}', self.id, cmd, error)
            self._daemon.io_loop.remove_timeout(timeout)
            client.close()
            if on_error:
                on_error(error)

        timeout = self._daemon.io_loop.add_timeout(time.time() + self.TIMEOUT, on_call_timeout)
        client = zerohub.AsyncRPCClient(self._cfg.player_rpc, io_loop=self._daemon.io_loop, name='codrestd')
        command_client = command.AsyncCommandRPCClient(client)
        command_client.call(cmd, on_response=on_call_response, on_error=on_call_error)


    def subscribe(self, connection):
        """Subscribe a SockJS connection to state updates.
        """

        self._subscribers.add(connection)
        self._daemon.log('player {}: client subscribing (count {})', self.id, len(self._subscribers))

        if not self._state_client:
            self._daemon.log('player {}: subscribing to player state updates ', self.id)

            self._current_state = None
            self._current_rip_state = None
            self._current_disc = None
            self._state_client = state.StateClient(
                self._cfg.state, io_loop=self._daemon.io_loop,
                on_state=self._on_state,
                on_rip_state=self._on_rip_state,
                on_disc=self._on_disc)

            # Fetch info immediately
            self.call('state', on_response=self._on_state)
            self.call('rip_state', on_response=self._on_rip_state)
            self.call('source', on_response=self._on_disc)

        else:
            connection.send({
                'id': self.id,
                'state': self._current_state,
                'rip_state': self._current_rip_state,
                'disc': self._current_disc
            })


    def unsubscribe(self, connection):
        """Unsubscribe a SockJS connection from state updates.
        """
        self._subscribers.discard(connection)
        self._daemon.log('player {}: client unsubscribing (count {})', self.id, len(self._subscribers))

        if not self._subscribers and self._state_client:
            self._daemon.log('player {}: unsubscribing from player state updates ', self.id)

            self._state_client.close()
            self._state_client = None
            self._current_state = None
            self._current_rip_state = None
            self._current_disc = None


    def _on_state(self, state):
        # Pass state through JSON serialization back to dict,
        # since sockjs-tornado expects objects that can be
        # serialized without any of the codplayer special stuff.

        self._current_state = json.loads(serialize.get_jsons(state))

        self._socket_router.broadcast(
            self._subscribers,
            {
                'id': self.id,
                'state': self._current_state
            })


    def _on_rip_state(self, rip_state):
        self._current_rip_state = json.loads(serialize.get_jsons(rip_state))

        self._socket_router.broadcast(
            self._subscribers,
            {
                'id': self.id,
                'rip_state': self._current_rip_state
            })


    def _on_disc(self, disc):
        self._current_disc = json.loads(serialize.get_jsons(disc))

        self._socket_router.broadcast(
            self._subscribers,
            {
                'id': self.id,
                'disc': self._current_disc
            })



class RestConfig(config.DaemonConfig):
    DEFAULT_FILE = os.path.join(sys.prefix, 'local/etc/codrest.conf')

    CONFIG_PARAMS = (
        serialize.Attr('database', str),
        serialize.Attr('host', str),
        serialize.Attr('port', int),
        serialize.Attr('players', list_type=RemotePlayer),
        )

    def __init__(self, config_file=None):
        super(RestConfig, self).__init__(config_file=config_file)
        for player in self.players:
            player.load_mq_config(self.config_path)


class DiscOverview(model.Disc):
    def __init__(self, disc):
        super(DiscOverview, self).__init__()

        self.disc_id = disc.disc_id
        self.mb_id = disc.mb_id
        self.cover_mb_id = disc.cover_mb_id
        self.tracks = len(disc.tracks)
        self.catalog = disc.catalog
        self.title = disc.title
        self.artist = disc.artist
        self.barcode = disc.barcode
        self.date = disc.date
        self.link_type = disc.link_type
        self.linked_disc_id = disc.linked_disc_id


class RestDaemon(Daemon):
    def __init__(self, cfg, database, debug = False):
        self._database = database
        self._debug_mode = debug
        super(RestDaemon, self).__init__(cfg, debug = debug)

    @property
    def database(self):
        return self._database


    @property
    def io_loop(self):
        # Just log errors on cod log file without quitting (as in the default daemon ioloop)
        if self._io_loop is None:
            self._io_loop = zerohub.IOLoop()
            self._io_loop.handle_callback_exception = self._log_exception

        return self._io_loop


    def setup_prefork(self):
        # Create sockets manually before fork so they can open privileged ports
        self._server_sockets = netutil.bind_sockets(port=self.config.port, address=self.config.host, reuse_port=True)
        for s in self._server_sockets:
            self.preserve_file(s)


    def run(self):
        # Cannot access IOLoop until after fork, since the epoll FD is lost otherwise

        params = { 'daemon': self }

        # Helper function to pass players into the connection handler
        def connection(*args):
            return PlayerClientConnection(self.config.players, *args)

        socket_router = SockJSRouter(connection, prefix='/client', io_loop=self.io_loop)

        urls = [
            web.URLSpec('^/discs$', DiscListHandler, params),
            web.URLSpec('^/discs/([^/]+)$', DiscHandler, params),
            web.URLSpec('^/discs/([^/]+)/musicbrainz$', MusicbrainzHandler, params),
            web.URLSpec('^/players$', PlayerListHandler, params),
            web.URLSpec('^/players/([^/]+)$', PlayerHandler, params),
            web.URLSpec('^/players/([^/]+)/([^/]+)$', PlayerCommandHandler, params),
            web.URLSpec('^/(.*)', web.StaticFileHandler, {
                'path': resource_filename('codplayer', 'data/dbadmin'),
                'default_filename': 'codadmin.html'
            })
        ]

        self._app = web.Application(
            socket_router.urls + urls,
            serve_traceback=True,
            compress_response=not self._debug_mode,
            static_hash_cache=not self._debug_mode,
            log_function=self._log_request)


        server = httpserver.HTTPServer(self._app, io_loop=self.io_loop)
        server.add_sockets(self._server_sockets)

        for p in self.config.players:
            p.start(self, socket_router)

        self.log('listening on {}:{}', self.config.host, self.config.port)
        self.io_loop.start()


    def _log_request(self, handler):
        status = handler.get_status()
        self.log('{0.method} {0.uri} {1} {0.remote_ip}', handler.request, status)


    def _log_exception(self, callback):
        self.log('Unhandled exception:\n{}', traceback.format_exc())


class BaseHandler(web.RequestHandler):
    def initialize(self, daemon):
        self._daemon = daemon
        self._database = daemon.database

    def _send_json(self, obj, pretty=True):
        self.set_header('Content-type', 'application/json')
        self.finish(serialize.get_jsons(obj, pretty=pretty))

    def log_exception(self, exc_type, exc_value, exc_tb):
        if not isinstance(exc_value, web.HTTPError):
            self._daemon.log('Unhandled exception:\n{}', ''.join(
                traceback.format_exception(exc_type, exc_value, exc_tb)))


class DiscListHandler(BaseHandler):
    """Return an array of DiscOverview JSON objects for all discs
    in the database.
    """

    def get(self):
        discs = []
        for db_id in self._database.iterdiscs_db_ids():
            try:
                disc = self._database.get_disc_by_db_id(db_id)
                if disc:
                    discs.append(DiscOverview(disc))
            except model.DiscInfoError, e:
                pass

        self._send_json(discs, pretty=False)


class DiscHandler(BaseHandler):
    """GET or PUT full model.ExtDisc JSON object for the disc with the
    provided Musicbrainz disc ID.
    """

    def get(self, disc_id):
        if not self._database.is_valid_disc_id(disc_id):
            raise web.HTTPError(400, 'Invalid disc_id')

        disc = self._database.get_disc_by_disc_id(disc_id)
        if disc is None:
            raise web.HTTPError(404, 'Unknown disc_id')

        self._send_json(model.ExtDisc(disc))


    def put(self, disc_id):
        if not self._database.is_valid_disc_id(disc_id):
            raise web.HTTPError(400, 'Invalid disc_id')

        if not self.request.body:
            raise web.HTTPError(400, 'Missing disc JSON')

        try:
            input_disc = serialize.load_jsons(model.ExtDisc, self.request.body)
        except serialize.LoadError as e:
            raise web.HTTPError(400, str(e))

        if disc_id != input_disc.disc_id:
            raise web.HTTPError(400, 'disc_id mismatch: got "{0}" in URL, "{1}" in JSON'.format(
                disc_id, input_disc.disc_id))

        db_disc = self._database.update_disc(input_disc)
        self._send_json(model.ExtDisc(db_disc))


class MusicbrainzHandler(BaseHandler):
    """Return an array of model.ExtDisc JSON objects containing
    all matching records from Musicbrainz.
    """

    def get(self, disc_id):
        try:
            musicbrainzngs.set_useragent('codplayer', version, 'https://github.com/petli/codplayer')

            # TODO: cache the response XML
            mb_dict = musicbrainzngs.get_releases_by_discid(
                disc_id, includes = ['recordings', 'artist-credits'])

            discs = model.ExtDisc.get_from_mb_dict(mb_dict, disc_id)
            if not discs:
                raise web.HTTPError(404, 'No Musicbrainz releases matching {0}'.format(disc_id))

            self._send_json(discs)

        except musicbrainzngs.WebServiceError, e:
            if e.cause and e.cause.code:
                # Pass on the response code
                raise web.HTTPError(e.cause.code, 'Musicbrainz web service error: {0}'.format(e))
            else:
                raise web.HTTPError(500, 'Musicbrainz web service error: {0}'.format(e))

        except musicbrainzngs.MusicBrainzError, e:
            raise web.HTTPError(500, 'Musicbrainz web service error: {0}'.format(e))


class PlayerListHandler(BaseHandler):
    def get(self):
        self._send_json([p.json for p in self._daemon.config.players])


class PlayerHandler(BaseHandler):
    def get(self, player_id):
        for p in self._daemon.config.players:
            if p.id == player_id:
                self._send_json(p.json)
                return

        raise web.HTTPError(404, 'Unknown player ID: {}'.format(player_id))


class PlayerCommandHandler(BaseHandler):
    @web.asynchronous
    def get(self, player_id, cmd):
        for p in self._daemon.config.players:
            if p.id == player_id:
                p.call(str(cmd),
                       on_response=self._on_player_response,
                       on_error=self._on_player_error)
                return

        raise web.HTTPError(404, 'Unknown player ID: {}'.format(player_id))

    post = get
    put = get

    def _on_player_response(self, response):
        if response:
            self._send_json(response)
        else:
            self.set_status(204)
            self.finish()


    def _on_player_error(self, error):
        if isinstance(error, command.CommandError):
            self.set_status(400, str(error))
        else:
            self.set_status(500, str(error))

        self.finish(str(error))


class PlayerClientConnection(SockJSConnection):
    def __init__(self, players, *args):
        self._players = players
        super(PlayerClientConnection, self).__init__(*args)

    def on_open(self, request):
        for p in self._players:
            p.subscribe(self)

    def on_close(self):
        for p in self._players:
            p.unsubscribe(self)

    def on_message(self, msg):
        pass
