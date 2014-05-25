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
    str_unicode = unicode
except NameError:
    # Python 3, then
    str_unicode = str
    

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


class Attr(object):
    """Define one attribute in a MAPPING table.
    """

    def __init__(self, name, value_type = None, list_type = None,
                 enum = None, optional = False):
        """name: attribute name

        value_type: expected type of the value.  Either a tuple that
        can be passed to isinstance(), or a class deriving from
        Serializable.

        list_type: the value should be a list where each element has
        this type (specified as for value_type).

        enum: if provided, a sequence of valid enum classes.

        optional: if True, don't raise an error if missing.
        """

        assert value_type or list_type or enum
        
        self.name = name
        self.value_type = value_type
        self.list_type = list_type
        self.enum = enum
        self.optional = optional
        

    def get_value_from_json(self, value):
        if self.value_type:
            return self._get_value(value, self.value_type)

        elif self.list_type:
            if not isinstance(value, list):
                raise LoadError('expected list for attribute {0}, got {1!r}'
                                .format(self.name, value))
            
            return [self._get_value(v, self.list_type) for v in value]

        elif self.enum:
            for cls in self.enum:
                if value == cls.__name__:
                    return cls
            else:
                raise LoadError('invalid class enum for attribute {0}, got {1}'
                                .format(self.name, value))
        else:
            assert False, 'this should not happen'


    def _get_value(self, value, value_type):
        if value is None:
            return value
            
        if isinstance(value_type, type) and issubclass(value_type, Serializable):
            if not isinstance(value, dict):
                raise LoadError('expected mapping for attribute {0}, got {1!r}'
                                .format(self.name, value))

            obj = value_type()
            populate_object(value, obj, obj.MAPPING)
            return obj
        else:
            # Special case: translate unicode to str
            if value_type is str and isinstance(value, str_unicode):
                value = str(value)

            if not isinstance(value, value_type):
                raise LoadError('expected type {0!r} for attribute {1}, got {2!r}'
                                .format(value_type, self.name, value))

            return value
        

def populate_object(src, dest, mapping):
    """Populate the object DEST by copying values from the dictionary SRC.

    MAPPPING is a sequence of Attr objects specifying how to map types
    from the SRC dictionary to the DEST object.

    Raises LoadError if a value is missing or is of the wrong type.
    """

    for attr in mapping:
        try:
            value = src[attr.name]
        except KeyError:
            if not attr.optional:
                raise LoadError('missing attribute: {0}'.format(attr.name))
        else:
            setattr(dest, attr.name, attr.get_value_from_json(value))


            

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
    

def get_jsons(obj, pretty = False):
    return json.dumps(obj, indent = 2 if pretty else None, sort_keys = pretty, cls = CodEncoder)

    
def load_json(cls, path):
    """Load JSON into a new object of type CLS from PATH, using CLS.MAPPING to populate it.

    Returns the object.
    """
    
    try:
        with open(path, 'rt') as f:
            raw = json.load(f)
    except (ValueError, IOError) as  e:
        raise LoadError('error reading JSON from {0}: {1}'.format(path, e))

    if raw is None:
        return None

    obj = cls()
    populate_object(raw, obj, cls.MAPPING)
    return obj
        

def load_jsons(cls, string):
    """Load JSON into a new object of type CLS from STRING, using CLS.MAPPING to populate it.

    Returns the object.
    """

    try:
        raw = json.loads(string)
    except ValueError as e:
        raise LoadError('malformed JSON: {0}'.format(e))

    if raw is None:
        return None

    obj = cls()
    populate_object(raw, obj, cls.MAPPING)
    return obj


def load_jsono(cls, raw):
    """Load JSON into a new object of type CLS from already parsed
    RAW json, using CLS.MAPPING to populate it.

    Returns the object.
    """
    
    if raw is None:
        return None

    obj = cls()
    populate_object(raw, obj, cls.MAPPING)
    return obj

        
