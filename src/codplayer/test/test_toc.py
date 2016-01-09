# codplayer - test the TOC parsing and merging code
# -*- coding: utf-8 -*-
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

from pkg_resources import resource_string
import unittest
import os
import discid

from .. import toc
from .. import model

msf_to_frames = model.PCM.msf_to_frames

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
        self.assertEqual(t.length, msf_to_frames('02:54:53'))
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
        self.assertEqual(t.length, msf_to_frames('02:54:53'))
        self.assertEqual(t.length, t.file_length)

        t = d.tracks[1]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset, msf_to_frames('02:54:53'))
        self.assertEqual(t.length, msf_to_frames('03:29:65'))
        self.assertEqual(t.length, t.file_length)

        t = d.tracks[2]
        self.assertEqual(t.number, 3)
        self.assertEqual(t.file_offset, msf_to_frames('06:24:43'))
        self.assertEqual(t.length, msf_to_frames('03:36:67'))
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
        self.assertEqual(t.length, msf_to_frames('02:54:53'))
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
                         msf_to_frames('03:27:10') +
                         msf_to_frames('03:48:35'))
        self.assertEqual(t.file_length, msf_to_frames('03:27:10'))
        self.assertEqual(t.pregap_offset, msf_to_frames('03:48:35'))
        self.assertEqual(t.pregap_silence, msf_to_frames('03:48:35'))


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
        self.assertEqual(t.length, msf_to_frames('02:54:53'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.pregap_offset, msf_to_frames('00:01:22'))

        # Indexes will have been translated from relative to pregap to
        # relative to track start

        self.assertEqual(len(t.index), 2)
        self.assertEqual(t.index[0], msf_to_frames('00:04:33'))
        self.assertEqual(t.index[1], msf_to_frames('00:06:22'))



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
        self.assertEqual(t.file_offset, msf_to_frames('03:15:63'))


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
        self.assertEqual(t.length, msf_to_frames('03:27:10'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.isrc, "GBAYE0000351")



class TestMergeBasicToc(unittest.TestCase):
    def test_overwrite_offsets(self):
        # This is one of the rare discs that actually have indices on
        # one track.  So we use that to make sure they are dropped
        # when merging, natch.
        d = model.DbDisc.from_string(resource_string(
            'codplayer.test', 'data/sonicyouth-daydreamnation.cod'))

        basic_disc = model.DbDisc.from_discid_disc(discid.put(
            1, 12, 255430 + 63503,
            [183, 31560, 48640, 83328, 114868, 132020, 166038,
             185768, 197898, 220320, 241283, 255430]))

        toc.merge_basic_toc(d, basic_disc)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset,
                         (183 - 2 * model.PCM.cd_frames_per_second) *
                         model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, 31377 * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.pregap_offset, 0)
        self.assertEqual(t.pregap_silence, 0)
        self.assertListEqual(t.index, [])
        self.assertEqual(t.title, 'Teen Age Riot')

        t = d.tracks[11]
        self.assertEqual(t.number, 12)
        self.assertEqual(t.file_offset,
                         (255430 - 2 * model.PCM.cd_frames_per_second) *
                         model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, 63503 * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.pregap_offset, 0)
        self.assertEqual(t.pregap_silence, 0)
        self.assertListEqual(t.index, [])
        self.assertEqual(t.title, 'Trilogy: The Wonder / Hyperstation / Eliminator Jr.')


class TestMergeFullToc(unittest.TestCase):
    def read_toc(self, testfile):
        return toc.parse_toc(
            resource_string('codplayer.test', 'data/' + testfile), 'dummyid')

    def test_plain_disc(self):
        """Addis Black Widow - Wait in Summer (single):
        Nothing fancy, just two tracks with regular separation.
        """

        d = model.DbDisc.from_discid_disc(discid.put(
            1, 2, 17357 + 14263, [150, 17357]))

        tocd = self.read_toc('abw-waitinsummer.toc')
        tocd.disc_id = d.disc_id

        toc.merge_full_toc(d, tocd)

        self.assertEqual(d.catalog, "5099767123812")

        self.assertEqual(len(d.tracks), 2)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, msf_to_frames('03:47:50'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.isrc, "GBDKA0100022")

        t = d.tracks[1]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset, msf_to_frames('03:47:50'))
        self.assertEqual(t.pregap_offset, msf_to_frames('00:01:57'))
        self.assertEqual(t.length, msf_to_frames('03:11:70'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.isrc, "GBDKA0100054")


    def test_hidden_track_at_start(self):
        """Kylie Minogue - Light Years:
        Has a hidden first track which is marked as silence in
        the full TOC.  It should be turned into track 0.
        """

        d = model.DbDisc.from_discid_disc(discid.put(
            1, 14, 240680 + 21557,
            [17285, 32875, 48862, 65165, 82972, 101780, 119790,
             135820, 154455, 171182, 189892, 205185, 221177, 240680]))

        tocd = self.read_toc('kylie-lightyears.toc')
        tocd.disc_id = d.disc_id

        toc.merge_full_toc(d, tocd)

        self.assertEqual(d.catalog, "0724352840021")

        self.assertEqual(len(d.tracks), 15)

        # Hidden track
        t = d.tracks[0]
        self.assertEqual(t.number, 0)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.pregap_offset, 0)
        self.assertEqual(t.length, msf_to_frames('03:48:35'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.isrc, None)

        # First regular track
        t = d.tracks[1]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, msf_to_frames('03:48:35'))
        self.assertEqual(t.length, msf_to_frames('03:27:10'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.pregap_silence, 0)
        self.assertEqual(t.pregap_offset, 0)
        self.assertEqual(t.isrc, "GBAYE0000351")

        # Subsequent tracks should have offsets somewhat changed
        t = d.tracks[2]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset, msf_to_frames('07:15:45'))
        self.assertEqual(t.length, msf_to_frames('03:32:42'))
        self.assertEqual(t.length, t.file_length)
        self.assertEqual(t.pregap_silence, 0)
        self.assertEqual(t.pregap_offset, msf_to_frames('00:00:55'))
        self.assertEqual(t.isrc, "GBAYE0000642")


    def test_use_cdtext(self):
        d = model.DbDisc.from_discid_disc(discid.put(
            1, 10, 143134 + 25354,
            [150, 14585, 29141, 44041, 58307, 80687, 96388, 112208,
             128048, 143134]))

        tocd = self.read_toc('cocteautwins-heavenorlasvegas.toc')
        tocd.disc_id = d.disc_id

        toc.merge_full_toc(d, tocd)

        self.assertEqual(d.title, 'HEAVEN OR LAS VEGAS')
        self.assertEqual(d.artist, 'THE COCTEAU TWINS')

        t = d.tracks[9]
        self.assertEqual(t.title, 'FROU-FROU FOXES IN MIDSUMMER FIRES')
        self.assertEqual(t.artist, None)


    def test_do_not_overwrite_track_info_with_cdtext(self):
        d = model.DbDisc.from_discid_disc(discid.put(
            1, 10, 143134 + 25354,
            [150, 14585, 29141, 44041, 58307, 80687, 96388, 112208,
             128048, 143134]))

        # Set some TOC info
        d.title = 'foo'
        d.artist = 'bar'
        d.tracks[0].title = 'gazonk'
        d.tracks[0].artist = 'bar'

        tocd = self.read_toc('cocteautwins-heavenorlasvegas.toc')
        tocd.disc_id = d.disc_id

        toc.merge_full_toc(d, tocd)

        self.assertEqual(d.title, 'foo')
        self.assertEqual(d.artist, 'bar')

        t = d.tracks[0]
        self.assertEqual(t.title, 'gazonk')
        self.assertEqual(t.artist, 'bar')


