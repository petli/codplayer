# codplayer - test the serialize module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import types

from .. import serialize

class DummyObject(object):
    pass

class TestPopulateObject(unittest.TestCase):
    def test_missing_attr(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'bar' },
                DummyObject(),
                [('gazonk', types.IntType)]
                )
        
    def test_incorrect_type(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'bar' },
                DummyObject(),
                [('foo', types.IntType)]
                )
        
    def test_populate(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'foo': 'bar',
              'gazonk': 17,
              'flag': True,
              'ignored': None,
              },
            obj,
            [('gazonk', types.IntType),
             ('foo', types.StringType),
             ('flag', types.BooleanType)]
            )

        self.assertEqual(obj.foo, 'bar')
        self.assertEqual(obj.gazonk, 17)
        self.assertIs(obj.flag, True)
        
        
