# codplayer - REST API using bottle.py
#
# Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

from pkg_resources import resource_filename

import bottle
import musicbrainzngs

from . import version
from . import db
from . import model
from . import serialize

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


def rest_app(config):
    app = bottle.Bottle()

    mydb = db.Database(config.database)

    static_dir = resource_filename('codplayer', 'data/dbadmin')

    @app.route('/discs')
    def server_discs():
        """Return an array of DiscOverview JSON objects for all discs
        in the database.
        """
        discs = []
        for db_id in mydb.iterdiscs_db_ids():
            try:
                disc = mydb.get_disc_by_db_id(db_id)
                if disc:
                    discs.append(DiscOverview(disc))
            except model.DiscInfoError, e:
                pass

        bottle.response.content_type = 'application/json'
        return serialize.get_jsons(discs, pretty = False)


    @app.get('/discs/<disc_id>')
    def server_disc(disc_id):
        """Return a full model.ExtDisc JSON object for the disc
        with the provided Musicbrainz disc ID.
        """
        if not mydb.is_valid_disc_id(disc_id):
            bottle.abort(400, 'Invalid disc_id')
            
        disc = mydb.get_disc_by_disc_id(disc_id)
        if disc is None:
            bottle.abort(404, 'Unknown disc_id')
            
        bottle.response.content_type = 'application/json'
        return serialize.get_jsons(model.ExtDisc(disc), pretty = True)


    @app.put('/discs/<disc_id>')
    def server_disc(disc_id):
        """Parse a model.ExtDisc JSON object and update the database
        record for the given Musicbrainz disc ID.
        """
        if not mydb.is_valid_disc_id(disc_id):
            bottle.abort(400, 'Invalid disc_id')
            
        if not bottle.request.json:
            bottle.abort(400, 'Missing disc JSON')
            
        input_disc = serialize.load_jsono(model.ExtDisc, bottle.request.json)

        if disc_id != input_disc.disc_id:
            bottle.abort(400, 'disc_id mismatch: got "{0}" in URL, "{1}" in JSON'.format(
                    disc_id, input_disc.disc_id))
            
        db_disc = mydb.update_disc(input_disc)

        bottle.response.content_type = 'application/json'
        return serialize.get_jsons(model.ExtDisc(db_disc), pretty = True)


    @app.get('/discs/<disc_id>/musicbrainz')
    def server_disc_musicbrainz(disc_id):
        """Return an array of model.ExtDisc JSON objects containing
        all matching records from Musicbrainz.
        """
        
        try:
            musicbrainzngs.set_useragent('codplayer', version, 'https://github.com/petli/codplayer')

            # TODO: cache the response XML
            mb_dict = musicbrainzngs.get_releases_by_discid(
                disc_id, includes = ['recordings', 'artist-credits'])

            discs = model.ExtDisc.get_from_mb_dict(mb_dict, disc_id)
            if not discs:
                bottle.abort(404, 'No Musicbrainz releases matching {0}'.format(disc_id))

            bottle.response.content_type = 'application/json'
            return serialize.get_jsons(discs, pretty = False)
            
        except musicbrainzngs.WebServiceError, e:
            if e.cause and e.cause.code:
                # Pass on the response code
                bottle.abort(e.cause.code, 'Musicbrainz web service error: {0}'.format(e))
            else:
                bottle.abort(500, 'Musicbrainz web service error: {0}'.format(e))
                
        except musicbrainzngs.MusicBrainzError, e:
            bottle.abort(500, 'Musicbrainz web service error: {0}'.format(e))


    @app.route('/players')
    def server_players():
        """Return an array of JSON objects for all configured players.
        """
        bottle.response.content_type = 'application/json'
        return serialize.get_jsons(config.players, pretty = True)


    # Serve static files from the Python package
    @app.route('/<filename:path>')
    def server_static(filename):
        return bottle.static_file(filename, root = static_dir)

    @app.route('/')
    def server_root():
        return bottle.static_file('codadmin.html', root = static_dir)
    
    return app
