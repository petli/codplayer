# codplayer - test the LCD formatting code
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import time

from .. import lcd
from ..state import State, RipState


class TestLCDFormatter16x2(unittest.TestCase):

    def setUp(self):
        self._formatter = lcd.LCDFormatter16x2()
        # Override LCD-specific characters
        self._formatter.PLAY = '>'
        self._formatter.PAUSE = '='


    def test_no_disc(self):
        #           1234567890abcdef  1234567890abcdef
        expected = "No disc         \n                "

        msg = self._formatter.format(State(state = State.NO_DISC),
                                     RipState(), None, time.time())

        self.assertEqual(msg, expected)


    def test_state_row(self):
        """Test the first row displaying the basic state."""

        # Define the expected first row for the possible states

        states = [
            # 1234567890abcdef
            ("Stop    9 tracks", State(state = State.STOP,
                                       no_tracks = 9)),
            ("Working 1/9...  ", State(state = State.WORKING,
                                       track = 1, no_tracks = 9)),
            ("Working 10/12...", State(state = State.WORKING,
                                       track = 10, no_tracks = 12)),
            ("> 1/9  0:10/3:20", State(state = State.PLAY,
                                       track = 1, no_tracks = 9,
                                       position = 10, length = 200)),
            ("= 1/9  0:10/3:20", State(state = State.PAUSE,
                                       track = 1, no_tracks = 9,
                                       position = 10, length = 200)),
            ("> 2/10 0:11/3:20", State(state = State.PLAY,
                                       track = 2, no_tracks = 10,
                                       position = 11, length = 200)),
            (">10/10 1:10/3:20", State(state = State.PLAY,
                                       track = 10, no_tracks = 10,
                                       position = 70, length = 200)),
            ("> 1/9 -0:01/3:20", State(state = State.PLAY,
                                       track = 1, no_tracks = 9, # pregap
                                       position = -1, length = 200)),
            (">10/10-0:01/3:20", State(state = State.PLAY,
                                       track = 10, no_tracks = 10, # pregap
                                       position = -1, length = 200)),
            (">1/9  9:59/12:30", State(state = State.PLAY,
                                       track = 1, no_tracks = 9,
                                       position = 599, length = 750)),
            (">1/9 10:00/12:30", State(state = State.PLAY,
                                       track = 1, no_tracks = 9,
                                       position = 600, length = 750)),
            (">1/10 9:59/12:30", State(state = State.PLAY,
                                       track = 1, no_tracks = 10,
                                       position = 599, length = 750)),
            (">1/10  10:00/12+", State(state = State.PLAY,
                                       track = 1, no_tracks = 10,
                                       position = 600, length = 750)),
            (">10/12  9:59/12+", State(state = State.PLAY,
                                       track = 10, no_tracks = 12,
                                       position = 599, length = 750)),
            (">10/12 10:00/12+", State(state = State.PLAY,
                                       track = 10, no_tracks = 12,
                                       position = 600, length = 750)),
            ]

        for row, state in states:
            row += '\nUnknown disc    '
            msg = self._formatter.format(state, RipState(), None, time.time())
            self.assertEqual(msg, row)


