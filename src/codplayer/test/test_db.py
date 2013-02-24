# codplayer - test the DB module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest

from .. import db

class TestDiscIDs(unittest.TestCase):
    DISC_ID = 'uP.sebZoiZSYakZh.g3coKrme8I-'
    DB_ID = 'b8ffac79b6688994986a4661fa0ddca0aae67bc2'

    def test_disc_id_to_hex(self):
        db_id = db.Database.disc_to_db_id(self.DISC_ID)
        self.assertEquals(db_id, self.DB_ID)

    def test_hex_to_disc_id(self):
        disc_id = db.Database.db_to_disc_id(self.DB_ID)
        self.assertEquals(disc_id, self.DISC_ID)


