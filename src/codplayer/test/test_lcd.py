# codplayer - test the LCD formatting code
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import time

from .. import lcd
from ..state import State, RipState
from .. import model

class TestLCDFormatter16x2(unittest.TestCase):

    def setUp(self):
        self._formatter = lcd.LCDFormatter16x2()
        # Override LCD-specific characters
        self._formatter.PLAY = '>'
        self._formatter.PAUSE = '='


    def test_no_disc(self):
        #           0123456789abcdef  0123456789abcdef
        expected = "No disc         \n                "

        msg = self._formatter.format(State(state = State.NO_DISC),
                                     RipState(), None, time.time())

        self.assertEqual(msg, expected)


    def test_state_row(self):
        """Test the first row displaying the basic state."""

        # Define the expected first row for the possible states

        states = [
            # 0123456789abcdef
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


    def test_null_disc_info(self):
        # Arrange a disc object with no info
        disc = model.ExtDisc()
        t = model.ExtTrack()
        t.number = 1
        disc.tracks = [t]

        state = State(state = State.PLAY, track = 1, no_tracks = 2,
                      position = 10, length = 200)
        state_line = '> 1/2  0:10/3:20\n'

        # Scroll disc title on new disc
        now = 0

        #                                   0123456789abcdef
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Unknown album   ')

        # Don't change yet
        msg = self._formatter.format(state, RipState(), disc, now + 0.5 * self._formatter.DISC_INFO_SWITCH_SPEED)
        self.assertEqual(msg, state_line + 'Unknown album   ')

        # But change now
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Unknown artist  ')

        # Don't change yet
        msg = self._formatter.format(state, RipState(), disc, now + 0.5 * self._formatter.DISC_INFO_SWITCH_SPEED)
        self.assertEqual(msg, state_line + 'Unknown artist  ')

        # But change now
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Unknown track   ')


    def test_disc_info(self):
        # Arrange test objects
        disc = model.ExtDisc()

        #              0123456789abcdef
        disc.artist = 'Test Disc Artist X'
        disc.title =  'Test Disc Title YZ'

        t1 = model.ExtTrack()
        t1.number = 1

        # Test prepending track number when it doesn't match state line
        # track number due to skipped tracks
        t2 = model.ExtTrack()
        t2.number = 3

        #           0123456789abcdef
        t1.title = 'Test Track 1 Title'
        t2.title = 'Track Title #3'

        disc.tracks = [t1, t2]

        state = State(state = State.PLAY, track = 1, no_tracks = 2,
                      position = 10, length = 200)
        state_line = '> 1/2  0:10/3:20\n'

        # Scroll disc title on new disc
        now = 0

        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Disc Title ')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'est Disc Title Y')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'st Disc Title YZ')

        now += self._formatter.SCROLL_PAUSE
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Disc Title ')

        # Then switch to scrolling the artist
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Disc Artist')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'est Disc Artist ')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'st Disc Artist X')

        now += self._formatter.SCROLL_PAUSE
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Disc Artist')

        # Finally to track title
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Track 1 Tit')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'est Track 1 Titl')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'st Track 1 Title')

        now += self._formatter.SCROLL_PAUSE
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Track 1 Tit')

        # And there it should remain
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + 'Test Track 1 Tit')

        # Until the second track
        now = 0
        state = State(state = State.PLAY, track = 2, no_tracks = 2,
                      position = 10, length = 200)
        state_line = '> 2/2  0:10/3:20\n'

        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + '3. Track Title #')

        now += self._formatter.SCROLL_SPEED
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + '3. rack Title #3')

        now += self._formatter.SCROLL_PAUSE
        msg = self._formatter.format(state, RipState(), disc, now)
        self.assertEqual(msg, state_line + '3. Track Title #')

