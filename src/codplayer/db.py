# codplayer - file system database interface
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Provide interfaces to working with the CD database in the file system.
"""

import os
import string
import base64
import re


class DatabaseError(Exception):
    def __init__(self, dir, msg = None, entry = None, exc = None):
        if entry:
            m = '%s (%s): ' % (dir, entry)
        else:
            m = '%s: ' % dir

        if msg:
            m += str(msg)
        elif exc:
            m += str(exc)
        else:
            m += 'unknown error'

        super(DatabaseError, self).__init__(m)


class Database(object):
    """Access the filesystem database of ripped discs.

    The database uses the following directory structure:

    DB_DIR/.codplayerdb
      Identifies that this is a database directory.  Contains a single
      number that is the version of the database format.

    DB_DIR/discs/
      Contains all ripped discs by a hex version of the Musicbrainz
      disc ID.

    DB_DIR/discs/0/
    ...
    DB_DIR/discs/9/
    DB_DIR/discs/a/
    ...
    DB_DIR/discs/f/
      Buckets for the disc directories, based on first four bits of
      the disc ID (the first hex character).

    DB_DIR/discs/b/b8ffac79b6688994986a4661fa0ddca0aae67bc2/
      Directory for a ripped disc, named by hex version of disc ID.
      Referenced as DISC_DIR below.

    The files of a disc are all based on the first eight characters of
    the hex ID, to aid in reconstructing a trashed database:

    DISC_DIR/b8ffac79.id
      Contains the Musicbrainz version of the disc ID.
      
    DISC_DIR/b8ffac79.cdr
      Raw audio data (PCM samples) from the disc.

    DISC_DIR/b8ffac79.toc
      TOC read by cdrdao from the disc.

    DISC_DIR/b8ffac79.cod (optional)
      If present, the cooked disc TOC with album information and track
      edits.
    """

    VERSION = 1

    VERSION_FILE = '.codplayerdb'
    DISC_DIR = 'discs'

    DISC_BUCKETS = tuple('0123456789abcdef')
    
    DISC_ID_SUFFIX = '.id'
    AUDIO_SUFFIX = '.cdr'
    ORIG_TOC_SUFFIX = '.toc'
    COOKED_TOC_SUFFIX = '.cod'


    #
    # Helper class methods
    #
    
    DISC_ID_TO_BASE64 = string.maketrans('._-', '+/=')
    BASE64_TO_DISC_ID = string.maketrans('+/=', '._-')

    VALID_DB_ID_RE = re.compile('^[0-9a-fA-F]{40}$')

    @classmethod
    def disc_to_db_id(cls, disc_id):
        """Translate a Musicbrainz Disc ID to database format."""

        id64 = disc_id.translate(cls.DISC_ID_TO_BASE64)
        idraw = base64.b64decode(id64)
        return base64.b16encode(idraw).lower()

    @classmethod
    def db_to_disc_id(cls, db_id):
        """Translate a database ID to Musicbrainz Disc ID."""

        idraw = base64.b16decode(db_id, True)
        id64 = base64.b64encode(idraw)
        return id64.translate(cls.BASE64_TO_DISC_ID)
    
    @classmethod
    def is_valid_db_id(cls, db_id):
        return cls.VALID_DB_ID_RE.match(db_id) is not None


    #
    # Database operations
    #

    @classmethod
    def init_db(cls, db_dir):
        """Initialise a database directory.

        @param db_dir: database top directory.
        """
        
        pass

    
    def __init__(self, db_dir):
        """Create an object accessing a database directory.

        @param db_dir: database top directory.

        @raise DatabaseError: if the directory structure is invalid
        """

        self.db_dir = db_dir

        try:
            # Must be a directory
            if not os.path.isdir(self.db_dir):
                raise DatabaseError(self.db_dir, 'no such directory')

            version_path = os.path.join(self.db_dir, self.VERSION_FILE)

            # Must have signature file
            if not os.path.isfile(version_path):
                raise DatabaseError(self.db_dir, 'missing version file',
                                    entry = self.VERSION_FILE)

            # Read first line to determine DB version
            f = open(version_path, 'rt')
            try:
                raw_version = f.readline()
                version = int(raw_version)
            except ValueError:
                raise DatabaseError(self.db_dir,
                                    'invalid version: %r' % raw_version,
                                    entry = self.VERSION_FILE)
                                    

            # Check that it is the expected version
            # (In the future: handle backward compatibility)

            if version != self.VERSION:
                raise DatabaseError(self.db_dir,
                                    'incompatible version: %d' % version,
                                    entry = self.VERSION_FILE)
                

        # translate into a DatabaseError
        except (IOError, OSError), e:
            raise DatabaseError(self.db_dir, exc = e)

