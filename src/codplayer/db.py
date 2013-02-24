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
      Directory for a ripped disc, named by disc ID (dots replaced by
      commas).  Referenced as DISC_DIR below.


    DISC_DIR/disc.id
      Contains the database disc ID, same as the directory name.
      
    DISC_DIR/disc.cdr
      Raw audio data (PCM samples) from the disc.

    DISC_DIR/disc.toc
      TOC read by cdrdao from the disc.
    """

    VERSION = 1

    ID_FILE = '.codplayerdb'
    DISC_DIR = 'discs'
    
    DISC_ID_FILE = 'disc.id'
    AUDIO_FILE = 'disc.cdr'
    TOC_FILE = 'disc.toc'


    @classmethod
    def init_db(cls, db_dir):
        """Initialise a database directory.

        @param db_dir: database top directory.
        """
        
        pass

    
    def __init__(self, db_dir):
        """Create a database object.

        @param db_dir: database top directory.
        """
        pass

        

    DISC_ID_TO_BASE64 = string.maketrans('._-', '+/=')
    BASE64_TO_DISC_ID = string.maketrans('+/=', '._-')

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
    
        
