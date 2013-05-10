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



class FOO(object):
    pass

class BAR(object):
    pass


class TestPopulateObject(unittest.TestCase):
    def test_missing_attr(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'bar' },
                DummyObject(),
                [('gazonk', int)]
                )
        
    def test_incorrect_type(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'bar' },
                DummyObject(),
                [('foo', int)]
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
            [('gazonk', int),
             ('foo', str),
             ('flag', bool)]
            )

        self.assertEqual(obj.foo, 'bar')
        self.assertEqual(obj.gazonk, 17)
        self.assertIs(obj.flag, True)
        
        
    def test_bad_enum(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'GAZONK' },
                DummyObject(),
                [('foo', serialize.ClassEnumType(FOO, BAR))]
                )

    def test_enum(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'foo': 'FOO',
              'bar': 'BAR' },
            obj,
            [('foo', serialize.ClassEnumType(FOO, BAR)),
             ('bar', serialize.ClassEnumType(FOO, BAR))]
            )

        self.assertIs(obj.foo, FOO)
        self.assertIs(obj.bar, BAR)
        
