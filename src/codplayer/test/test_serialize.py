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


class Structure(serialize.Serializable):
    MAPPING = (
        serialize.Attr('number', int),
        )


class TestPopulateObject(unittest.TestCase):
    def test_missing_attr(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'bar' },
                DummyObject(),
                [serialize.Attr('gazonk', int)]
                )
        
    def test_incorrect_type(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'bar' },
                DummyObject(),
                [serialize.Attr('foo', int)]
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
            [serialize.Attr('gazonk', int),
             serialize.Attr('foo', str),
             serialize.Attr('flag', bool)]
            )

        self.assertEqual(obj.foo, 'bar')
        self.assertEqual(obj.gazonk, 17)
        self.assertIs(obj.flag, True)
        
        
    def test_optional(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'foo': 'bar' },
            obj,
            [serialize.Attr('foo', str),
             serialize.Attr('opt1', int, optional = True),
             serialize.Attr('opt2', int, optional = True, default = 17)]
            )

        self.assertEqual(obj.foo, 'bar')
        self.assertEqual(obj.opt1, None)
        self.assertEqual(obj.opt2, 17)


    def test_unicode_to_str(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'foo': u'bar' },
            obj,
            [serialize.Attr('foo', str)]
            )

        self.assertTrue(isinstance(obj.foo, str))
        self.assertEqual(obj.foo, 'bar')


    def test_unicode(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'foo': u'bar\u20ac' },
            obj,
            [serialize.Attr('foo', serialize.str_unicode)]
            )

        self.assertTrue(isinstance(obj.foo, serialize.str_unicode))
        self.assertEqual(obj.foo, u'bar\u20ac')


    def test_bad_enum(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'foo': 'GAZONK' },
                DummyObject(),
                [serialize.Attr('foo', enum = (FOO, BAR))]
                )


    def test_enum(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'foo': 'FOO',
              'bar': 'BAR' },
            obj,
            [serialize.Attr('foo', enum = (FOO, BAR)),
             serialize.Attr('bar', enum = (FOO, BAR))]
            )

        self.assertIs(obj.foo, FOO)
        self.assertIs(obj.bar, BAR)

        
    def test_structure(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'value': { 'number': 17 } },
            obj,
            [serialize.Attr('value', Structure)]
            )

        self.assertIsInstance(obj.value, Structure)
        self.assertEqual(obj.value.number, 17)
        

    def test_bad_structure(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'value': 17 },
                DummyObject(),
                [serialize.Attr('value', Structure)]
                )
        

    def test_list(self):
        obj = DummyObject()

        serialize.populate_object(
            { 'values': [17, 42, 39] },
            obj,
            [serialize.Attr('values', list_type = int)]
            )

        self.assertIsInstance(obj.values, list)
        self.assertListEqual(obj.values, [17, 42, 39])

    def test_bad_list(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'values': 17 },
                DummyObject(),
                [serialize.Attr('values', list_type = int)]
                )

    def test_bad_list_value(self):
        with self.assertRaises(serialize.LoadError):
            serialize.populate_object(
                { 'values': ['foo'] },
                DummyObject(),
                [serialize.Attr('values', list_type = int)]
                )

