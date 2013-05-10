# codplayer - test the DB module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import os
import tempfile

from .. import db, model

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

        # Dir should now exist and not contain those files 
        self.assertTrue(os.path.isdir(path))
        self.assertFalse(os.path.exists(audio_file))
        self.assertFalse(os.path.exists(toc_file))

        # But should have the disc ID file
        self.assertTrue(os.path.isfile(self.db.get_id_path(self.DB_ID)))

        # Getting the disc should not return anything, since the files
        # are missing

        disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNone(disc)


        # Create dummy files to check that file is returned fine

        open(audio_file, 'wb').close()

        f = open(toc_file, 'wt')
        f.write("""
TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "{0}.cdr" 0 02:54:53
""".format(self.DB_ID[:8]))
        f.close()

        disc = self.db.get_disc_by_disc_id(self.DISC_ID)
        self.assertIsNotNone(disc)
        
        self.assertEqual(disc.disc_id, self.DISC_ID)

        self.assertEqual(len(disc.tracks), 1)

        t = disc.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))
        
        
