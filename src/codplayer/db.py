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
import types

from . import model
from . import serialize


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

    DISC_DIR/b8ffac79.cod
      A serialized model.DbDisc recording the current state and
      information about the disc.
    """

    VERSION = 1

    VERSION_FILE = '.codplayerdb'
    DISC_DIR = 'discs'

    DISC_BUCKETS = tuple('0123456789abcdef')
    
    DISC_ID_SUFFIX = '.id'
    AUDIO_SUFFIX = '.cdr'
    ORIG_TOC_SUFFIX = '.toc'
    DISC_INFO_SUFFIX = '.cod'

    #
    # Helper class methods
    #
    
    DISC_ID_TO_BASE64 = string.maketrans('._-', '+/=')
    BASE64_TO_DISC_ID = string.maketrans('+/=', '._-')

    VALID_DB_ID_RE = re.compile('^[0-9a-fA-F]{40}$')
    VALID_DISC_ID_RE = re.compile('^[-._0-9a-zA-Z]{28}$')

    @classmethod
    def disc_to_db_id(cls, disc_id):
        """Translate a Musicbrainz Disc ID to database format."""

        id64 = str(disc_id).translate(cls.DISC_ID_TO_BASE64)
        idraw = base64.b64decode(id64)
        return base64.b16encode(idraw).lower()

    @classmethod
    def db_to_disc_id(cls, db_id):
        """Translate a database ID to Musicbrainz Disc ID."""

        idraw = base64.b16decode(db_id, True)
        id64 = base64.b64encode(idraw)
        return str(id64).translate(cls.BASE64_TO_DISC_ID)
    
    @classmethod
    def is_valid_db_id(cls, db_id):
        return cls.VALID_DB_ID_RE.match(db_id) is not None

    @classmethod
    def is_valid_disc_id(cls, disc_id):
        return cls.VALID_DISC_ID_RE.match(disc_id) is not None


    @classmethod
    def bucket_for_db_id(cls, db_id):
        return db_id[0]


    @classmethod
    def filename_base(cls, db_id):
        return db_id[:8]


    #
    # Database operations
    #

    @classmethod
    def init_db(cls, db_dir):
        """Initialise a database directory.

        @param db_dir: database top directory, must exist and be empty

        @raise DatabaseError: if directory doesn't exist or isn't empty
        """

        try:
            if not os.path.isdir(db_dir):
                raise DatabaseError(db_dir, 'no such dir')

            if os.listdir(db_dir):
                raise DatabaseError(db_dir, 'dir is not empty')

            f = open(os.path.join(db_dir, cls.VERSION_FILE), 'wt')
            f.write('%d\n' % cls.VERSION)
            f.close()

            disc_top_dir = os.path.join(db_dir, cls.DISC_DIR)
            os.mkdir(disc_top_dir)
            
            for b in cls.DISC_BUCKETS:
                os.mkdir(os.path.join(disc_top_dir, b))

        # translate into a DatabaseError
        except (IOError, OSError), e:
            raise DatabaseError(self.db_dir, exc = e)

    
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
                

            # Must have disc top dir

            disc_top_dir = os.path.join(self.db_dir, self.DISC_DIR)

            if not os.path.isdir(disc_top_dir):
                raise DatabaseError(self.db_dir, 'missing disc dir')


            # Must have all bucket dirs
            for b in self.DISC_BUCKETS:
                d = os.path.join(disc_top_dir, b)

                if not os.path.isdir(d):
                    raise DatabaseError(self.db_dir, 'missing bucket dir',
                                        entry = b)


        # translate into a DatabaseError
        except (IOError, OSError), e:
            raise DatabaseError(self.db_dir, exc = e)


    def get_disc_dir(self, db_id):
        """@return the path to the directory for a disc, identified by
        the db_id."""
        
        return os.path.join(self.db_dir,
                            self.DISC_DIR,
                            self.bucket_for_db_id(db_id),
                            db_id)

    def get_id_file(self, db_id):
        return self.filename_base(db_id) + self.DISC_ID_SUFFIX


    def get_audio_file(self, db_id):
        return self.filename_base(db_id) + self.AUDIO_SUFFIX

    def get_orig_toc_file(self, db_id):
        return self.filename_base(db_id) + self.ORIG_TOC_SUFFIX

    def get_disc_info_file(self, db_id):
        return self.filename_base(db_id) + self.DISC_INFO_SUFFIX

    def get_id_path(self, db_id):
        return os.path.join(self.get_disc_dir(db_id),
                            self.get_id_file(db_id))


    def get_audio_path(self, db_id):
        return os.path.join(self.get_disc_dir(db_id),
                            self.get_audio_file(db_id))

    def get_orig_toc_path(self, db_id):
        return os.path.join(self.get_disc_dir(db_id),
                            self.get_orig_toc_file(db_id))

    def get_disc_info_path(self, db_id):
        return os.path.join(self.get_disc_dir(db_id),
                            self.get_disc_info_file(db_id))
        

    def iterdiscs_db_ids(self):
        """@return an iterator listing the datbase IDs of all discs in
        the database.

        This method only looks at the directories, and may return IDs
        for discs that can't be opened (e.g. because it is in the
        progress of being ripped.)
        """

        disc_top_dir = os.path.join(self.db_dir, self.DISC_DIR)

        for b in self.DISC_BUCKETS:
            d = os.path.join(disc_top_dir, b)

            try:
                for f in os.listdir(d):
                    if self.is_valid_db_id(f) and self.bucket_for_db_id(f) == b:
                        yield f

            # translate into a DatabaseError
            except OSError, e:
                raise DatabaseError(self.db_dir, exc = e, entry = b)


    def get_disc_by_disc_id(self, disc_id):
        """@return a Disc basted on a MusicBrainz disc ID, or None if
        not found in database.
        """
        
        return self.get_disc_by_db_id(self.disc_to_db_id(disc_id))


    def get_disc_by_db_id(self, db_id):
        """@return a Disc basted on a database ID, or None if not
        found in database.
        """

        if not self.is_valid_db_id(db_id):
            raise ValueError('invalid DB ID: {0!r}'.format(db_id))

        path = self.get_disc_dir(db_id)

        disc_info_file = self.get_disc_info_path(db_id)

        if not os.path.exists(disc_info_file):
            # If no file, no disc
            return None

        try:
            disc = serialize.load_json(model.DbDisc, disc_info_file)
        except serialize.LoadError, e:
            raise DatabaseError(self.db_dir, 'error reading disc info file: {0}'.format(e))

        # 1.0 had a bug where the full data file path was saved, and
        # not just the file name itself.  This breaks playback if the
        # database path changes, so repair any incorrect paths here.
        disc.data_file_name = os.path.basename(disc.data_file_name)

        return disc


    def create_disc_dir(self, db_id):
        """Create a directory for a new disc to be ripped into the
        database, identified by db_id.

        @return the path to the disc directory
        """

        path = self.get_disc_dir(db_id)
            
        # Be forgiving if the dir already exists, to allow aborted
        # rips to be restarted easily

        if not os.path.isdir(path):
            try:
                os.mkdir(path)
            except OSError, e:
                raise DatabaseError(self.db_dir, 'error creating disc dir {0}: {1}'.format(
                        path, e))


        fbase = self.filename_base(db_id)

        # Write the disc ID
        try:
            disc_id_path = self.get_id_path(db_id)
            f = open(disc_id_path, 'wt')
            f.write(self.db_to_disc_id(db_id) + '\n')
            f.close()
        except IOError, e:
            raise DatabaseError(self.db_dir, 'error writing disc ID to {0}: {1}'.format(
                    disc_id_path, e))

        return path

    
    def save_disc_info(self, disc):
        """Save new disc info, overwriting anything existing.
        """
        db_id = self.disc_to_db_id(disc.disc_id)
        try:
            serialize.save_json(disc, self.get_disc_info_path(db_id))
        except serialize.SaveError, e:
            raise DatabaseError(self.db_dir, str(e))


    def create_disc(self, disc):
        """Create a directory for a new disc and save the initial disc object.
        """
        db_id = self.disc_to_db_id(disc.disc_id)
        self.create_disc_dir(db_id)
        self.save_disc_info(disc)


    def update_disc(self, ext_disc):
        """Update the database information about a disc, based on the
        information provided in EXT_DISC.

        This must be a model.ExtDisc instance, with the same number of
        tracks, as the database record.  (I.e. you can't attempt to
        remove tracks here.)

        Fields set to None in EXT_DISC are not updated, to protect
        against losing information if the information came from an
        outdated client.  To erase a text field, set it to the empty
        string.

        Returns the updated DbDisc object.
        """

        if not isinstance(ext_disc, model.ExtDisc):
            raise ValueError('update requires an ExtDisc object: {0!r}'.format(ext_disc))

        if not self.is_valid_disc_id(ext_disc.disc_id):
            raise ValueError('invalid disc ID: {0!r}'.format(ext_disc.disc_id))
            
        db_id = self.disc_to_db_id(ext_disc.disc_id)
        db_disc = self.get_disc_by_db_id(db_id)

        if db_disc is None:
            raise DatabaseError(self.db_dir, 'attempting to update an unknown disc: {0}'.format(ext_disc.disc_id))

        # Disc ok, update attributes
        update_db_object(db_disc, ext_disc)


        # Update the tracks, checking that nothing fishy is happening
        if serialize.attr_populated(ext_disc, 'tracks'):
            if len(ext_disc.tracks) != len(db_disc.tracks):
                raise ValueError('update expected {0} tracks, got {1}'.format(
                        len(db_disc.tracks), len(ext_disc.tracks)))

            for db_track, ext_track in zip(db_disc.tracks, ext_disc.tracks):
                if not isinstance(ext_track, model.ExtTrack):
                    raise ValueError('update requires an ExtTrack object: {0!r}'.format(ext_track))

                if db_track.number != ext_track.number:
                    raise ValueError('update expected track number {0}, got {1}'.format(
                            db_track.number, ext_track.number))

                # Track ok, update attribute
                update_db_object(db_track, ext_track)
            

        # Save new record
        serialize.save_json(db_disc, self.get_disc_info_path(db_id))

        return db_disc

        
def update_db_object(db_obj, ext_obj):
    for attr in db_obj.MUTABLE_ATTRS:
        value = getattr(ext_obj, attr)
        if serialize.attr_populated(ext_obj, attr):
            if isinstance(value, types.StringTypes):
                value = value.strip()
            setattr(db_obj, attr, value)
