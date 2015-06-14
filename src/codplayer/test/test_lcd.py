# codplayer - test the LCD formatting code
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest

from .. import lcd

class TestLCDFormatter16x2(unittest.TestCase):
    def setUp(self):
        self._formatter = lcd.LCDFormatter16x2()

    def test_stopped(self):
        pass
