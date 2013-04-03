# codplayer - classes for (de)serialization for db etc
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Wrappers around basic json serialization and deserialization.
"""

import json
import types
import tempfile
import os
import stat


# By saving to temporary files and moving them in place, file writing
# is much safer and can change the file to readonly when complete.
SAVE_PERMISSIONS = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class LoadError(Exception):
    pass

class SaveError(Exception):
    pass


def populate_object(src, dest, mapping):
    """Populate the object DEST by copying values from the dictionary SRC.

    MAPPPING is a sequence of tuples specyfing which attributes to set
    and the expected types for them: (attribute, type)

    Raises LoadError if a value is missing or is of the wrong type.
    """

    for attr, desttype in mapping:
        try:
            value = src[attr]
        except KeyError:
            raise LoadError('missing attribute: {0}'.format(attr))

        if type(value) != desttype:
            raise LoadError('expected type {0} for attribute {1}, got {2!r}'
                            .format(desttype.__name__, attr, value))

        setattr(dest, attr, value)
            

class CodEncoder(json.JSONEncoder):
    """Custom enconder that extends the behavior to suit codplayer:

    - Classes are serialized by name, to handle the various state and
      format IDs
    """

    def default(self, obj):
        if type(obj) is types.ClassType:
            return obj.__name__

        super(CodEncoder, self).default(obj)
        

    
def save_json(obj, path):
    """Serialize OBJ (really its __dict__) to json and save it in a file in PATH.
    """

    # TODO: also handle UTF-8 properly

    try:
        dir, base = os.path.split(path)

        # Work with a temporary file in the same directory as the
        # state file, so we know we can safely rename it later
        with tempfile.NamedTemporaryFile(
            dir = dir,
            prefix = base + '.',
            mode = 'wt',
            delete = False) as f:

            temp_path = f.name
            json.dump(obj.__dict__, f, indent = 2, sort_keys = True, cls = CodEncoder)

        os.chmod(temp_path, SAVE_PERMISSIONS)
        os.unlink(path)
        os.rename(temp_path, path)

    except (IOError, OSError), e:
        raise SaveError('error saving to {0}: {1}'.format(path, e))
    
    
