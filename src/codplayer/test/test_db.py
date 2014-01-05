# codplayer - test the DB module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import os
import tempfile

from .. import db, model
from .. import serialize


class TestDiscIDs(unittest.TestCase):
    DISC_ID = 'uP.sebZoiZSYakZh.g3coKrme8I-'
    DB_ID = 'b8ffac79b6688994986a4661fa0ddca0aae67bc2'

    def test_disc_id_to_hex(self):
        db_id = db.Database.disc_to_db_id(self.DISC_ID)
        self.assertEquals(db_id, self.DB_ID)

    def test_hex_to_disc_id(self):
        disc_id = db.Database.db_to_disc_id(self.DB_ID)
        self.assertEquals(disc_id, self.DISC_ID)

    def test_valid_db_id_re(self):
        self.assertFalse(db.Database.is_valid_db_id(''))
        self.assertTrue(db.Database.is_valid_db_id(self.DB_ID))
        self.assertFalse(db.Database.is_valid_db_id(self.DB_ID[1:]))
        self.assertFalse(db.Database.is_valid_db_id('x' + self.DB_ID[1:]))
        self.assertFalse(db.Database.is_valid_db_id(self.DISC_ID))



class TestDir(object):
    """Mixin class to setup an empty test database directory and tear
    it down with any valid contents afterwards.  If there's something
    that seems to be a foreign file, it stop and fails.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        super(TestDir, self).setUp()

    def tearDown(self):
        super(TestDir, self).tearDown()

        # Careful cleanup
        for f in os.listdir(self.test_dir):

            # Top dir files
            if f in (db.Database.VERSION_FILE, ):
                os.remove(os.path.join(self.test_dir, f))
                
            # Top dir subdirs
            elif f == db.Database.DISC_DIR:
                self.tearDownDiscTopDir(os.path.join(self.test_dir, f))

            else:
                self.fail('unexpected db dir entry in %s: %s'
                          % (self.test_dir, f))

        os.rmdir(self.test_dir)


    def tearDownDiscTopDir(self, d):
        for f in os.listdir(d):
            if f in db.Database.DISC_BUCKETS:
                self.tearDownDiscBucket(os.path.join(d, f))
            else:
                self.fail('unexpected disc dir entry in %s: %s' % (d, f))

        os.rmdir(d)                


    def tearDownDiscBucket(self, d):
        for f in os.listdir(d):
            if db.Database.is_valid_db_id(f):
                self.tearDownDiscDir(os.path.join(d, f))
            else:
                self.fail('unexpected bucket dir entry in %s: %s' % (d, f))

        os.rmdir(d)


    def tearDownDiscDir(self, d):
        for f in os.listdir(d):
            # Cheat a bit and now only look at the file suffix
            s = os.path.splitext(f)[1]

            if s in (db.Database.DISC_ID_SUFFIX,
                     db.Database.AUDIO_SUFFIX,
                     db.Database.ORIG_TOC_SUFFIX,
                     db.Database.COOKED_TOC_SUFFIX,
                     '.log',
                     ):
                os.remove(os.path.join(d, f))
            else:
                self.fail('unexpected disc dir entry in %s: %s' % (d, f))

        os.rmdir(d)


#
# Negative test cases on init or opening DB dir
#
        
class TestNonexistingDir(unittest.TestCase):
    def test_init_non_existing_dir(self):
        with self.assertRaises(db.DatabaseError):
            db.Database.init_db('/no/such/directory')

    def test_open_non_existing_dir(self):
        with self.assertRaises(db.DatabaseError):
            d = db.Database('/no/such/directory')



class TestInvalidDir(TestDir, unittest.TestCase):
    def test_init_non_empty_dir(self):
        f = open(os.path.join(self.test_dir, db.Database.VERSION_FILE), 'wt')
        f.write('foo\n')
        f.close()

        with self.assertRaises(db.DatabaseError):
            db.Database.init_db(self.test_dir)

    def test_open_empty_dir(self):
        with self.assertRaises(db.DatabaseError):
            d = db.Database(self.test_dir)

    def test_invalid_version_file(self):
        f = open(os.path.join(self.test_dir, db.Database.VERSION_FILE), 'wt')
        f.write('foo\n')
        f.close()

        with self.assertRaises(db.DatabaseError):
            d = db.Database(self.test_dir)
    
    def test_incompatible_version(self):
        f = open(os.path.join(self.test_dir, db.Database.VERSION_FILE), 'wt')
        f.write('4711\n')
        f.close()

        with self.assertRaises(db.DatabaseError):
            d = db.Database(self.test_dir)
    

#
# Positive test case setting up dir, verify by opening it
#

class TestInitDir(TestDir, unittest.TestCase):
    def test_init_dir(self):
        db.Database.init_db(self.test_dir)
        d = db.Database(self.test_dir)
        
        # The database should be empty
        disc_ids = list(d.iterdiscs_db_ids())
        self.assertEqual(len(disc_ids), 0)

        
#
# Test adding discs and fetching them
#

class TestDiscAccess(TestDir, unittest.TestCase):
    DISC_ID = 'uP.sebZoiZSYakZh.g3coKrme8I-'
    DB_ID = 'b8ffac79b6688994986a4661fa0ddca0aae67bc2'

    def setUp(self):
        super(TestDiscAccess, self).setUp()
        db.Database.init_db(self.test_dir)
        self.db = db.Database(self.test_dir)
        
    def test_create_disc_dir(self):
        path = self.db.create_disc_dir(self.DB_ID)

        self.assertEqual(path, self.db.get_disc_dir(self.DB_ID))

        audio_file = self.db.get_audio_path(self.DB_ID)
        toc_file = self.db.get_orig_toc_path(self.DB_ID)
        cooked_toc_file = self.db.get_cooked_toc_path(self.DB_ID)

        # Dir should now exist and not contain those files 
        self.assertTrue(os.path.isdir(path))
        self.assertFalse(os.path.exists(audio_file))
        self.assertFalse(os.path.exists(toc_file))
        self.assertFalse(os.path.exists(cooked_toc_file))

        # But should have the disc ID file
        self.assertTrue(os.path.isfile(self.db.get_id_path(self.DB_ID)))

        # Getting the disc should not return anything, since the files
        # are missing

        disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNone(disc)


        # Create dummy files to check that file is returned fine

        open(audio_file, 'wb').close()

        with open(toc_file, 'wt') as f:
            f.write("""
TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "{0}.cdr" 0 02:54:53
""".format(self.DB_ID[:8]))

        disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(disc)
        
        self.assertEqual(disc.disc_id, self.DISC_ID)
        self.assertIs(disc.title, None)

        self.assertEqual(len(disc.tracks), 1)

        t = disc.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))
        
        # Now add some info and save as a cooked TOC and see that it
        # hides the original TOC

        disc.artist = u'Disc artist'
        disc.title = u'Disc title'
        t.artist = u'Track artist'
        t.title = u'Track title'
        
        serialize.save_json(disc, cooked_toc_file)

        disc2 = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(disc2)
        
        self.assertEqual(disc2.disc_id, self.DISC_ID)
        self.assertEqual(disc2.artist, u'Disc artist')
        self.assertEqual(disc2.title, u'Disc title')

        self.assertEqual(len(disc2.tracks), 1)

        t2 = disc2.tracks[0]
        self.assertEqual(t2.number, 1)
        self.assertEqual(t2.file_offset, 0)
        self.assertEqual(t2.length, model.PCM.msf_to_frames('02:54:53'))
        self.assertEqual(t2.artist, u'Track artist')
        self.assertEqual(t2.title, u'Track title')
        

#
# Test that the disc information can be updated
#
        
class TestDiscUpdate(TestDir, unittest.TestCase):
    DISC_ID = 'uP.sebZoiZSYakZh.g3coKrme8I-'
    DB_ID = 'b8ffac79b6688994986a4661fa0ddca0aae67bc2'

    def setUp(self):
        super(TestDiscUpdate, self).setUp()
        db.Database.init_db(self.test_dir)
        self.db = db.Database(self.test_dir)
        
        path = self.db.create_disc_dir(self.DB_ID)
        audio_file = self.db.get_audio_path(self.DB_ID)
        toc_file = self.db.get_orig_toc_path(self.DB_ID)

        open(audio_file, 'wb').close()

        with open(toc_file, 'wt') as f:
            f.write("""
TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "{0}.cdr" 0 02:54:53
""".format(self.DB_ID[:8]))


    def test_update_invalid_disc(self):
        with self.assertRaises(ValueError):
            self.db.update_disc(None)

        ext_disc = model.ExtDisc()
        ext_disc.disc_id = 'invalid'
        with self.assertRaises(ValueError):
            self.db.update_disc(ext_disc)

        ext_disc.disc_id = 'Fy3nZdEhBmXzkiolzR08Xk5rPQ4-'
        with self.assertRaises(db.DatabaseError):
            self.db.update_disc(ext_disc)


    def test_update_disc_info(self):
        orig_disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(orig_disc)

        # All changes must come through an ExtDisc
        ext_disc = model.ExtDisc(orig_disc)
        
        # These ones are allowed to be changed
        ext_disc.artist = u'Disc artist'
        ext_disc.title = u'Disc title'
        ext_disc.catalog = u'Catalog'
        ext_disc.barcode = u'Barcode'
        ext_disc.release_date = u'2010-10-10'
        
        self.db.update_disc(ext_disc)

        new_disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(new_disc)

        # All disc info should be updated (except ID)
        self.assertEqual(new_disc.disc_id, self.DISC_ID)
        self.assertEqual(new_disc.artist, u'Disc artist')
        self.assertEqual(new_disc.title, u'Disc title')
        self.assertEqual(new_disc.catalog, u'Catalog')
        self.assertEqual(new_disc.barcode, u'Barcode')
        self.assertEqual(new_disc.release_date, u'2010-10-10')

        # Track should not have changed
        t = new_disc.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))


        # Now test just changing one value, by setting the others to None
        ext_disc.artist = u'New disc artist'
        ext_disc.title = None
        ext_disc.catalog = None
        ext_disc.barcode = None
        ext_disc.release_date = None
        
        self.db.update_disc(ext_disc)

        new_disc2 = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(new_disc2)

        # All disc info should be updated (except ID)
        self.assertEqual(new_disc2.disc_id, self.DISC_ID)
        self.assertEqual(new_disc2.artist, u'New disc artist')
        self.assertEqual(new_disc2.title, u'Disc title')
        self.assertEqual(new_disc2.catalog, u'Catalog')
        self.assertEqual(new_disc2.barcode, u'Barcode')
        self.assertEqual(new_disc2.release_date, u'2010-10-10')


    def test_update_invalid_track(self):
        orig_disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(orig_disc)

        # All changes must come through an ExtDisc
        ext_disc = model.ExtDisc(orig_disc)

        # Can't play around with track numbers
        self.assertEqual(ext_disc.tracks[0].number, 1)
        ext_disc.tracks[0].number = 2

        with self.assertRaises(ValueError):
            self.db.update_disc(ext_disc)

        # Or remove tracks
        ext_disc.tracks = []
        with self.assertRaises(ValueError):
            self.db.update_disc(ext_disc)


    def test_update_track_info(self):
        orig_disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(orig_disc)

        # All changes must come through an ExtDisc
        ext_disc = model.ExtDisc(orig_disc)

        ext_track = ext_disc.tracks[0]

        # These can change
        ext_track.artist = u'Track artist'
        ext_track.title = u'Track title'
        ext_track.isrc = u'ISRC'

        # But these are ignored
        ext_track.length = 4711
        ext_track.pregap_offset = 23
        ext_track.index = [42, 43]

        self.db.update_disc(ext_disc)

        new_disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(new_disc)

        new_track = new_disc.tracks[0]

        # So these should have changed
        self.assertEqual(new_track.artist, u'Track artist')
        self.assertEqual(new_track.title, u'Track title')
        self.assertEqual(new_track.isrc, u'ISRC')

        # These should not have changed
        self.assertEqual(new_track.number, 1)
        self.assertEqual(new_track.file_offset, 0)
        self.assertEqual(new_track.length, model.PCM.msf_to_frames('02:54:53'))
        self.assertListEqual(new_track.index, [])

        
