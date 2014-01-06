# codplayer - REST API using bottle.py
#
# Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import bottle

from . import db
from . import model
from . import serialize

class DiscOverview(model.Disc):
    def __init__(self, disc):
        super(DiscOverview, self).__init__()

        self.disc_id = disc.disc_id
        self.tracks = len(disc.tracks)
        self.catalog = disc.catalog
        self.title = disc.title
        self.artist = disc.artist
        self.barcode = disc.barcode
        self.release_date = disc.release_date


def rest_app(config):
    app = bottle.Bottle()

    mydb = db.Database(config.database)
    
    @app.route('/discs')
    def server_discs():
        discs = []
        for db_id in mydb.iterdiscs_db_ids():
            try:
                disc = mydb.get_disc_by_db_id(db_id)
                if disc:
                    discs.append(DiscOverview(disc))
            except model.DiscInfoError, e:
                pass

        bottle.response.content_type = 'application/json'
        return serialize.get_jsons(discs, pretty = True)


    @app.get('/discs/<disc_id>')
    def server_disc(disc_id):
        if not mydb.is_valid_disc_id(disc_id):
            bottle.abort(400, 'Invalid disc_id')
            
        disc = mydb.get_disc_by_disc_id(disc_id)
        if disc is None:
            bottle.abort(404, 'Unknown disc_id')
            
        bottle.response.content_type = 'application/json'
        return serialize.get_jsons(model.ExtDisc(disc), pretty = False)


    @app.put('/discs/<disc_id>')
    def server_disc(disc_id):
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
        return serialize.get_jsons(model.ExtDisc(db_disc), pretty = False)
            

    if config.static_dir:
        # Support simple setups where the web UI is provided by this
        # server instance too
        @app.route('/<filename:path>')
        def server_static(filename):
            return bottle.static_file(filename, root = config.static_dir)

        @app.route('/')
        def server_root():
            return bottle.static_file('codadmin.html', root = config.static_dir)
    
    return app
