# codplayer - test (parts of) the player module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest

from .. import player, model

class CommandReaderWrapper(player.CommandReader):
    def __init__(self, *read_strings):
        super(CommandReaderWrapper, self).__init__(0)
        self.read_strings = list(read_strings)

    def read_data(self):
        d = self.read_strings[0]
        del self.read_strings[0]
        return d
        

class TestCommandReader(unittest.TestCase):
    def test_(self):
        cr = CommandReaderWrapper(
            'foo\n',		# single self-contained command
             ' cmd  2 ',	# no newline, so no command read
             '\n',		# newline trigger command
             'cmd 3\ncmd 4\nc', # two commands and start of next
             'md 5\n',		# terminate the last command
             )

        # Get foo
        cmds = list(cr.handle_data())
        self.assertListEqual(cmds, [['foo']])

        # Get nothing
        cmds = list(cr.handle_data())
        self.assertListEqual(cmds, [])

        # Get cmd 2
        cmds = list(cr.handle_data())
        self.assertListEqual(cmds, [['cmd', '2']])

        # Get cmd 3 and 4
        cmds = list(cr.handle_data())
        self.assertListEqual(cmds, [['cmd', '3'],
                                    ['cmd', '4']])

        # Get cmd 5
        cmds = list(cr.handle_data())
        self.assertListEqual(cmds, [['cmd', '5']])
        

class TestAudioPacket(unittest.TestCase):

    def test_no_pregap_or_index(self):

        t = model.Track()
        t.file_offset = 5000
        t.length = 50000

        p = player.AudioPacket(t, 2000, 1000)

        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, 2000)
        self.assertEqual(p.rel_pos, 2000)
        self.assertEqual(p.length, 1000)
        self.assertEqual(p.file_pos, 5000 + 2000)

        
    def test_pregap_and_index(self):

        t = model.Track()
        t.file_offset = 5000
        t.length = 50000
        t.pregap_offset = 3000
        t.index = [8000, 15000]

        # In pregap
        p = player.AudioPacket(t, 2000, 1000)

        self.assertEqual(p.index, 0)
        self.assertEqual(p.abs_pos, 2000)
        self.assertEqual(p.rel_pos, -1000)
        self.assertEqual(p.file_pos, 5000 + 2000)

        # Index 1, normal part of track
        p = player.AudioPacket(t, 4000, 1000)

        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, 4000)
        self.assertEqual(p.rel_pos, 1000)
        self.assertEqual(p.file_pos, 5000 + 4000)
        
        # Index 2
        p = player.AudioPacket(t, 10000, 1000)

        self.assertEqual(p.index, 2)
        self.assertEqual(p.abs_pos, 10000)
        self.assertEqual(p.rel_pos, 7000)
        self.assertEqual(p.file_pos, 5000 + 10000)

        # Index 3
        p = player.AudioPacket(t, 15000, 1000)

        self.assertEqual(p.index, 3)
        self.assertEqual(p.abs_pos, 15000)
        self.assertEqual(p.rel_pos, 12000)
        self.assertEqual(p.file_pos, 5000 + 15000)
        
        
    def test_silent_pregap(self):

        t = model.Track()
        t.file_offset = 5000
        t.length = 50000
        t.pregap_offset = 3000
        t.pregap_silence = 2000

        # In silent part of pregap
        p = player.AudioPacket(t, 1000, 1000)

        self.assertEqual(p.index, 0)
        self.assertEqual(p.abs_pos, 1000)
        self.assertEqual(p.rel_pos, -2000)
        self.assertEqual(p.file_pos, None)
        
        # In disc part of pregap
        p = player.AudioPacket(t, 2500, 500)

        self.assertEqual(p.index, 0)
        self.assertEqual(p.abs_pos, 2500)
        self.assertEqual(p.rel_pos, -500)
        self.assertEqual(p.file_pos, 5000 + 500)
        

class TestAudioSplitter(unittest.TestCase):

    def test_unedited_disc(self):

        toc = '''
// First track have pregap silence (which will be ignored anyway)
TRACK AUDIO
TWO_CHANNEL_AUDIO
SILENCE 00:00:40
FILE "data.cdr" 0 00:01:00
START 00:00:40


// Second track have pregap from file
TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
FILE "data.cdr" 00:01:00 00:01:00
START 00:00:30


// Third track have no pregap
TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
FILE "data.cdr" 00:02:00 00:00:17
'''
        
        disc = model.Disc.from_toc(toc, 'testId')

        # Work with three packets per second, i.e. 25 frames per
        # packet, to make the test case reasonably easy to write
        splitter = player.AudioPacket.iterate(disc, 0, 3)
        
        def ftos(frames): return frames * model.PCM.samples_per_frame


        # First track will result in three audio packets (1 second of
        # sound)
        t = disc.tracks[0]

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, ftos(40))
        self.assertEqual(p.rel_pos, 0)
        self.assertEqual(p.length, ftos(25))
        self.assertEqual(p.file_pos, 0)

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, ftos(40 + 25))
        self.assertEqual(p.rel_pos, ftos(25))
        self.assertEqual(p.length, ftos(25))
        self.assertEqual(p.file_pos, ftos(25))

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, ftos(40 + 50))
        self.assertEqual(p.rel_pos, ftos(50))
        self.assertEqual(p.length, ftos(25))
        self.assertEqual(p.file_pos, ftos(50))


        # Second track will result in 25+5 frames pregap packet and
        # 25+20 frames main packets

        t = disc.tracks[1]

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 0)
        self.assertEqual(p.abs_pos, 0)
        self.assertEqual(p.rel_pos, ftos(-30))
        self.assertEqual(p.length, ftos(25))
        self.assertEqual(p.file_pos, ftos(75))

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 0)
        self.assertEqual(p.abs_pos, ftos(25))
        self.assertEqual(p.rel_pos, ftos(-5))
        self.assertEqual(p.length, ftos(5))
        self.assertEqual(p.file_pos, ftos(75 + 25))

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, ftos(30))
        self.assertEqual(p.rel_pos, 0)
        self.assertEqual(p.length, ftos(25))
        self.assertEqual(p.file_pos, ftos(75 + 30))

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, ftos(55))
        self.assertEqual(p.rel_pos, ftos(25))
        self.assertEqual(p.length, ftos(20))
        self.assertEqual(p.file_pos, ftos(75 + 55))


        # Third track will just be a 17 frame packet
        t = disc.tracks[2]

        p = splitter.next()
        self.assertIsNotNone(p)
        self.assertIs(p.track, t)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.abs_pos, 0)
        self.assertEqual(p.rel_pos, 0)
        self.assertEqual(p.length, ftos(17))
        self.assertEqual(p.file_pos, ftos(150))

        # Reached end of disc
        with self.assertRaises(StopIteration):
            splitter.next()
