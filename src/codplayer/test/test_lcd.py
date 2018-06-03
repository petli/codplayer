# codplayer - test the LCD formatting code
#
# Copyright 2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import time

from .. import lcd
from ..state import State, RipState, AlbumInfo, SongInfo
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

        msg, update = self._formatter.format(State(state = State.NO_DISC),
                                             RipState(), time.time())

        self.assertEqual(msg, expected)
        self.assertIsNone(update)


    def test_state_row(self):
        """Test the first row displaying the basic state."""

        # Define the expected first row for the possible states

        states = [
            # 0123456789abcdef
            ("Player shut down", State(state = State.OFF)),
            ("Stop    9 tracks", State(state = State.STOP, disc_id = 'foo',
                                       no_tracks = 9)),
            ("Working 1/9...  ", State(state = State.WORKING, disc_id = 'foo',
                                       track = 1, no_tracks = 9)),
            ("Working 10/12...", State(state = State.WORKING, disc_id = 'foo',
                                       track = 10, no_tracks = 12)),
            ("> 1/9  0:10/3:20", State(state = State.PLAY, disc_id = 'foo',
                                       track = 1, no_tracks = 9,
                                       position = 10, length = 200)),
            ("= 1/9  0:10/3:20", State(state = State.PAUSE, disc_id = 'foo',
                                       track = 1, no_tracks = 9,
                                       position = 10, length = 200)),
            ("> 2/10 0:11/3:20", State(state = State.PLAY, disc_id = 'foo',
                                       track = 2, no_tracks = 10,
                                       position = 11, length = 200)),
            (">10/10 1:10/3:20", State(state = State.PLAY, disc_id = 'foo',
                                       track = 10, no_tracks = 10,
                                       position = 70, length = 200)),
            ("> 1/9 -0:01/3:20", State(state = State.PLAY, disc_id = 'foo',
                                       track = 1, no_tracks = 9, # pregap
                                       position = -1, length = 200)),
            (">10/10-0:01/3:20", State(state = State.PLAY, disc_id = 'foo',
                                       track = 10, no_tracks = 10, # pregap
                                       position = -1, length = 200)),
            (">1/9  9:59/12:30", State(state = State.PLAY, disc_id = 'foo',
                                       track = 1, no_tracks = 9,
                                       position = 599, length = 750)),
            (">1/9 10:00/12:30", State(state = State.PLAY, disc_id = 'foo',
                                       track = 1, no_tracks = 9,
                                       position = 600, length = 750)),
            (">1/10 9:59/12:30", State(state = State.PLAY, disc_id = 'foo',
                                       track = 1, no_tracks = 10,
                                       position = 599, length = 750)),
            (">1/10  10:00/12+", State(state = State.PLAY, disc_id = 'foo',
                                       track = 1, no_tracks = 10,
                                       position = 600, length = 750)),
            (">10/12  9:59/12+", State(state = State.PLAY, disc_id = 'foo',
                                       track = 10, no_tracks = 12,
                                       position = 599, length = 750)),
            (">10/12 10:00/12+", State(state = State.PLAY, disc_id = 'foo',
                                       track = 10, no_tracks = 12,
                                       position = 600, length = 750)),
            ]

        for row, state in states:
            row += '\n                '
            msg, update = self._formatter.format(state, RipState(), time.time())
            self.assertEqual(msg, row)
            self.assertIsNone(update)


    def test_disc_info(self):
        #                       0123456789abcdef
        album_info = AlbumInfo('Test Disc Title YZ',
                               'Test Disc Artist X')

        #                       0123456789abcdef
        track1_info = SongInfo('Test Track 1 Title',
                               'Test Disc Artist X')

        # Test prepending track number when it doesn't match state line
        # track number due to skipped tracks. TODO!

        track2_info = SongInfo('Track Title #3',
                               'Test Disc Artist X')

        state = State(state = State.PLAY, track = 1, no_tracks = 2,
                      position = 10, length = 200, disc_id = 'foo',
                      album_info = album_info, song_info = track1_info)

        state_line = '> 1/2  0:10/3:20\n'

        # Scroll disc title on new disc
        now = 0

        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Disc Title ')

        # Don't change yet
        msg, update = self._formatter.format(state, RipState(), now + 0.5 * self._formatter.SCROLL_PAUSE)
        self.assertEqual(msg, state_line + 'Test Disc Title ')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'est Disc Title Y')

        now += self._formatter.SCROLL_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'st Disc Title YZ')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Disc Title ')

        # Don't change yet
        msg, update = self._formatter.format(state, RipState(), now + 0.5 * self._formatter.DISC_INFO_SWITCH_SPEED)
        self.assertEqual(msg, state_line + 'Test Disc Title ')

        # Then switch to scrolling the artist
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Disc Artist')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'est Disc Artist ')

        now += self._formatter.SCROLL_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'st Disc Artist X')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Disc Artist')

        # Finally to track title
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Track 1 Tit')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'est Track 1 Titl')

        now += self._formatter.SCROLL_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'st Track 1 Title')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Track 1 Tit')

        # And there it should remain
        now += self._formatter.DISC_INFO_SWITCH_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test Track 1 Tit')

        # TODO: handle offset track numbers
        return

        # Until the second track
        now = 0
        state = State(state = State.PLAY, track = 2, no_tracks = 2,
                      position = 10, length = 200, disc_id = 'foo',
                      album_info = album_info, song_info = track2_info)

        state_line = '> 2/2  0:10/3:20\n'

        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + '3. Track Title #')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + '3. rack Title #3')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + '3. Track Title #')


    def test_ripping(self):
        #                      0123456789abcdef
        track_info = SongInfo('Track Title 1', None)

        state = State(state = State.PLAY, track = 1, no_tracks = 2,
                      position = 10, length = 200, disc_id = 'foo',
                      song_info = track_info)

        state_line = '> 1/2  0:10/3:20\n'

        rip_state = RipState(state = RipState.AUDIO, progress = 5)

        # Will have to scroll since the rip state takes up place
        now = 0

        #                                   0123456789abcdef
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Track Title   5%')

        # Update progress, and scroll a step
        rip_state.progress = 15
        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'rack Title 1 15%')

        # Switch to TOC, and reset scroll
        rip_state = RipState(state = RipState.TOC)
        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Track Title  TOC')


    def test_player_errors(self):
        state = State(state = State.WORKING, track = 10, no_tracks = 12, disc_id = 'foo')
        state_line = 'Working 10/12...\n'

        # Scroll error continuously
        now = 0

        # Initial display is just disc info
        msg, update = self._formatter.format(state, RipState(), now)
        #                                   0123456789abcdef
        self.assertEqual(msg, state_line + '                ')
        self.assertIsNone(update)

        # Switch to error message immediately
        #              0123456789abcdef
        state.error = 'Test error message'

        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test error messa')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'est error messag')

        now += self._formatter.SCROLL_SPEED
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'st error message')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'Test error messa')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + 'est error messag')

        # Drop back to (empty) disc info when error clears
        state.error = None
        msg, update = self._formatter.format(state, RipState(), now)
        self.assertEqual(msg, state_line + '                ')
        self.assertIsNone(update)


    def test_rip_errors(self):
        state = State(state = State.WORKING, track = 10, no_tracks = 12, disc_id = 'foo')

        rip_state = State(state = RipState.TOC)

        state_line = 'Working 10/12...\n'

        # Scroll error continuously
        now = 0

        # Initial display is just disc info
        msg, update = self._formatter.format(state, rip_state, now)
        #                                   0123456789abcdef
        self.assertEqual(msg, state_line + '             TOC')
        self.assertIsNone(update)

        #                  0123456789ab
        rip_state.error = 'Test rip error'

        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Test rip err TOC')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'est rip erro TOC')

        now += self._formatter.SCROLL_SPEED
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'st rip error TOC')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Test rip err TOC')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'est rip erro TOC')

        # Drop back to (empty) disc info when error clears
        rip_state.error = None
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + '             TOC')
        self.assertIsNone(update)


    def test_multiple_errors(self):
        state = State(state = State.WORKING, track = 10, no_tracks = 12, disc_id = 'foo',
                      error = 'Player')
        rip_state = State(state = RipState.TOC, error = 'Ripper')

        state_line = 'Working 10/12...\n'

        # Scroll messages continously
        now = 0

        #                                   0123456789abcdef
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Player; Ripp TOC')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'layer; Rippe TOC')

        now += self._formatter.SCROLL_SPEED
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'ayer; Ripper TOC')

        now += self._formatter.SCROLL_PAUSE
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Player; Ripp TOC')

        # If player error now clears, switch to rip error only
        state.error = None
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + 'Ripper       TOC')
        self.assertIsNone(update)

        # And when that clears, back to (empty) disc info
        rip_state.error = None
        msg, update = self._formatter.format(state, rip_state, now)
        self.assertEqual(msg, state_line + '             TOC')
        self.assertIsNone(update)


class TestGPIO_LCDFactory(unittest.TestCase):
    def setUp(self):
        self._lcd_factory = lcd.GPIO_LCDFactory(
            led = 7, rs = 17, en = 27, d4 = 22, d5 = 23, d6 = 24, d7 = 25, backlight = 18,

            # Remap a single char to ensure it's index is known
            custom_chars = {
                '\xe5': (0x4,0x0,0xe,0x1,0xf,0x11,0xf,0x0),
            }
        )

    def test_encode_simplify_unicode(self):
        encoder = self._lcd_factory.get_text_encoder()

        text = encoder(u'\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u2013\u2014\u2026')
        self.assertEqual(text, '\'\'\'`"""---...')

    def test_encode_replace_unknown(self):
        encoder = self._lcd_factory.get_text_encoder()

        text = encoder(u'Sign \u201c\u262e\u201c the Times')
        self.assertEqual(text, 'Sign "?" the Times')

    def test_encode_custom_chars(self):
        encoder = self._lcd_factory.get_text_encoder()

        text = encoder(u'\xe5\xe4')
        self.assertEqual(text, '\x02\xe4')
