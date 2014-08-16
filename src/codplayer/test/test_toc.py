# codplayer - test the TOC parsing and merging code
# -*- coding: utf-8 -*-
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

from pkg_resources import resource_string
import unittest
import os

from .. import toc
from .. import model


class TestDiscFromToc(unittest.TestCase):
    def test_no_tracks(self):
        toc_data = '''
CD_DA
'''
        with self.assertRaises(toc.TOCError):
            toc.parse_toc(toc_data, 'testId')


    def test_catalog_and_basic_track(self):
        # Test ignoring data tracks too
        toc_data = '''
CD_DA

CATALOG "0123456789012"

TRACK MODE1
DATAFILE "foo.dat"

TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53
'''
        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(d.disc_id, 'testId')

        self.assertEqual(d.catalog, "0123456789012")
        self.assertEqual(d.data_file_name, "data.cdr")
        self.assertEqual(d.data_file_format, model.RAW_CD)
        self.assertEqual(d.audio_format, model.PCM)


        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))
        self.assertEqual(t.length, t.file_length)


    def test_multiple_tracks(self):
        toc_data = '''
CD_DA

TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53

TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
FILE "data.cdr" 02:54:53 03:29:65

TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
FILE "data.cdr" 06:24:43 03:36:67
'''
        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(d.catalog, None)
        self.assertEqual(d.data_file_name, "data.cdr")
        self.assertEqual(d.data_file_format, model.RAW_CD)
        self.assertEqual(d.audio_format, model.PCM)


        self.assertEqual(len(d.tracks), 3)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))
        self.assertEqual(t.length, t.file_length)

        t = d.tracks[1]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset, model.PCM.msf_to_frames('02:54:53'))
        self.assertEqual(t.length, model.PCM.msf_to_frames('03:29:65'))
        self.assertEqual(t.length, t.file_length)

        t = d.tracks[2]
        self.assertEqual(t.number, 3)
        self.assertEqual(t.file_offset, model.PCM.msf_to_frames('06:24:43'))
        self.assertEqual(t.length, model.PCM.msf_to_frames('03:36:67'))
        self.assertEqual(t.length, t.file_length)


    def test_ignore_comments(self):
        # Test ignoring data tracks too
        toc_data = '''
// CATALOG "0123456789012"

TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53 // foo bar

 // TRACK AUDIO
  // TWO_CHANNEL_AUDIO
// FILE "data.cdr" 02:54:53 03:29:65
'''
        d = toc.parse_toc(toc_data, 'testId')

        self.assertIsNone(d.catalog)

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))
        self.assertEqual(t.length, t.file_length)



    def test_pregap_silence(self):
        # Hidden track on Kylie Minogue, Light Years.  This
        # cdrdao-based code wouldn't be able to find and play it...
        toc_data = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
SILENCE 03:48:35
FILE "data.cdr" 0 03:27:10
START 03:48:35
'''
        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length,
                         model.PCM.msf_to_frames('03:27:10') +
                         model.PCM.msf_to_frames('03:48:35'))
        self.assertEqual(t.file_length, model.PCM.msf_to_frames('03:27:10'))
        self.assertEqual(t.pregap_offset, model.PCM.msf_to_frames('03:48:35'))
        self.assertEqual(t.pregap_silence, model.PCM.msf_to_frames('03:48:35'))


    def test_start_index(self):
        toc_data = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53
START 00:01:22
INDEX 00:03:11
INDEX 00:05:00
'''
        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('02:54:53'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.pregap_offset, model.PCM.msf_to_frames('00:01:22'))

        # Indexes will have been translated from relative to pregap to
        # relative to track start

        self.assertEqual(len(t.index), 2)
        self.assertEqual(t.index[0], model.PCM.msf_to_frames('00:04:33'))
        self.assertEqual(t.index[1], model.PCM.msf_to_frames('00:06:22'))



    def test_cdtext(self):
        toc_data = '''
CD_DA

CD_TEXT {
  // Comment inside text block
  LANGUAGE_MAP {
    1: 2
    // Will use language 0, which is English
    10: EN 2 : 3
  }
  LANGUAGE 10 {
    TITLE "Disc title"
    PERFORMER "Disc artist"
    GENRE { 0,  0,  0}
    SIZE_INFO { 1,  1, 22,  0, 29, 20,  0,  0,  0,  0,  0,  1,
                0,  0,  0,  0,  0,  0,  0,  3, 52,  0,  0,  0,
                0,  0,  0,  0,  9,  0,  0,  0,  0,  0,  0,  0}
  }
}

TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
CD_TEXT {
  LANGUAGE 1 {
    TITLE "will be skipped"
    PERFORMER "will be skipped"
  }

  LANGUAGE 10 {
    TITLE "Title track 1"
    PERFORMER "Artist track 1"
  }
}
FILE "data.cdr" 0 03:15:63

TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
CD_TEXT {
  LANGUAGE 10 {
    TITLE "Title track 2"
    PERFORMER "Artist track 2"
  }

  LANGUAGE 1 {
    TITLE "will be skipped"
    PERFORMER "will be skipped"
  }
}
FILE "data.cdr" 03:15:63 03:17:47
'''

        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(len(d.tracks), 2)
        self.assertEqual(d.data_file_name, "data.cdr")

        self.assertEqual(d.title, 'Disc title')
        self.assertEqual(d.artist, 'Disc artist')

        t = d.tracks[0]
        self.assertEqual(t.title, 'Title track 1')
        self.assertEqual(t.artist, 'Artist track 1')
        self.assertEqual(t.file_offset, 0)

        t = d.tracks[1]
        self.assertEqual(t.title, 'Title track 2')
        self.assertEqual(t.artist, 'Artist track 2')
        self.assertEqual(t.file_offset, model.PCM.msf_to_frames('03:15:63'))


    def test_cdtext_no_language_map(self):
        toc_data = '''
CD_DA

CD_TEXT {
  LANGUAGE 10 {
    TITLE "Disc title"
    PERFORMER "Disc artist"
  }
}

TRACK AUDIO
NO COPY
NO PRE_EMPHASIS
TWO_CHANNEL_AUDIO
CD_TEXT {
  LANGUAGE 1 {
    TITLE "will be skipped"
    PERFORMER "will be skipped"
  }

  LANGUAGE 10 {
    TITLE "Title track 1"
    PERFORMER "Artist track 1"
  }
}
FILE "data.cdr" 0 03:15:63
'''

        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(len(d.tracks), 1)
        self.assertEqual(d.data_file_name, "data.cdr")

        self.assertEqual(d.title, 'Disc title')
        self.assertEqual(d.artist, 'Disc artist')

        t = d.tracks[0]
        self.assertEqual(t.title, 'Title track 1')
        self.assertEqual(t.artist, 'Artist track 1')
        self.assertEqual(t.file_offset, 0)


    def test_track_isrc(self):
        toc_data = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
ISRC "GBAYE0000351"
FILE "data.cdr" 0 03:27:10
'''
        d = toc.parse_toc(toc_data, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('03:27:10'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.isrc, "GBAYE0000351")


