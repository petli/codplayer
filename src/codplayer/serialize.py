# codplayer - classes for (de)serialization for db etc
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Wrappers around basic json serialization and deserialization.
n"""

import json
import types
import tempfile
import os
import stat


try:
    string = unicode
except NameError:
    # Python 3, then
    string = str
    

# By saving to temporary files and moving them in place, file writing
# is much safer and can change the file to readonly when complete.
SAVE_PERMISSIONS = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class LoadError(Exception):
    pass

class SaveError(Exception):
    pass


class Serializable(object):
    """All classes that should be serialized must inherit this class.

    To be able to deserialise from JSON, it must be possible to
    instantiate an object without any parameters and the class must
    define a MAPPING attribute which will be passed to
    populate_object.
    """
    pass


class ClassEnumType(object):
    """Used to list valid classes used as enums when deserializing.
    """
    def __init__(self, *classes):
        self.classes = classes
    

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

        setattr(dest, attr, get_value_from_json(attr, desttype, value))

def get_value_from_json(attr, desttype, value):
        if value is None:
            return value
            
        elif isinstance(desttype, ClassEnumType):
            for cls in desttype.classes:
                if value == cls.__name__:
                    return cls
            else:
                raise LoadError('invalid class enum for attribute {0}, got {1}'
                                .format(attr, value))
                    
        elif isinstance(desttype, type) and issubclass(desttype, Serializable):
            if not isinstance(value, dict):
                raise LoadError('expected mapping for attribute {0}, got {1!r}'
                                .format(attr, value))
                
            obj = desttype()
            populate_object(value, obj, obj.MAPPING)
            return obj

        elif isinstance(desttype, list):
            assert len(desttype) == 1

            if not isinstance(value, list):
                raise LoadError('expected list for attribute {0}, got {1!r}'
                                .format(attr, value))
            
            subtype = desttype[0]
            return [get_value_from_json(attr, subtype, v) for v in value]
            
        else:
            if not isinstance(value, desttype):
                raise LoadError('expected type {0} for attribute {1}, got {2!r}'
                                .format(desttype.__name__, attr, value))

            return value
            

class CodEncoder(json.JSONEncoder):
    """Custom enconder that extends the behavior to suit codplayer:

    - Classes are serialized by name, to handle the various state and
      format IDs
    """

    def default(self, obj):
        if type(obj) is types.ClassType:
            return obj.__name__

        if isinstance(obj, Serializable):
            return obj.__dict__

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

            json.dump(obj, f, indent = 2, sort_keys = True, cls = CodEncoder)

        os.chmod(temp_path, SAVE_PERMISSIONS)

        try:
            os.unlink(path)
        except OSError:
            pass
        
        os.rename(temp_path, path)

    except (IOError, OSError), e:
        raise SaveError('error saving to {0}: {1}'.format(path, e))
    
    
def load_json(cls, path):
    """Load JSON into a new object of type CLS from PATH, using CLS.MAPPING to populate it.

    Returns the object.
    """
    
    try:
        with open(path, 'rt') as f:
            raw = json.load(f)
    except IOError, e:
        raise LoadError('error reading JSON from {0}: {1}'.format(path, e))

    obj = cls()
    populate_object(raw, obj, cls.MAPPING)
    return obj
        
