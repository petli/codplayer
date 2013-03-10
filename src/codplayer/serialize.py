# codplayer - classes for (de)serialization for db etc
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Wrappers around basic json serialization and deserialization.
"""

import json


class LoadError(Exception):
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
            

    
