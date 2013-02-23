# codplayer - test the DB module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest

from .. import db

class TestMSF(unittest.TestCase):
    def test_1s(self):
        s = db.PCM.msf_to_samples('00:01:00')
        self.assertEquals(s, db.PCM.rate)

    def test_full(self):
        s = db.PCM.msf_to_samples('08:17:74')
        self.assertEquals(s, (8 * 60 + 17) * db.PCM.rate + 74 * 588)


class TestDiscFromToc(unittest.TestCase):
    def test_no_tracks(self):
        toc = '''
CD_DA
'''
        with self.assertRaises(db.DiscInfoError):
            db.Disc.from_toc(toc)


    def test_catalog_and_basic_track(self):
        # Test ignoring data tracks too
        toc = '''
CD_DA

CATALOG "0123456789012"

TRACK MODE1
DATAFILE "foo.dat"

TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53
'''
        disc = db.Disc.from_toc(toc)

        self.assertEqual(disc.catalog, "0123456789012")
        self.assertEqual(disc.data_file_name, "data.cdr")
        self.assertEqual(disc.data_file_format, db.RAW_CD)
        self.assertEqual(disc.data_sample_format, db.PCM)


        self.assertEqual(len(disc.tracks), 1)

        t = disc.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, db.PCM.msf_to_samples('02:54:53'))
        

