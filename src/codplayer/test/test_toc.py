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



class MusicbrainzDiscDummy(object):
    def __init__(self, tracks, disc_id = 'testId'):
        self.tracks = tracks
        self.disc_id = disc_id

    def getId(self):
        return self.disc_id

    def getTracks(self):
        return self.tracks


class TestMergeBasicToc(unittest.TestCase):
    def test_overwrite_offsets(self):
        # This is one of the rare discs that actually have indices on
        # one track.  So we use that to make sure they are dropped
        # when merging, natch.
        d = model.DbDisc.from_string(resource_string(
            'codplayer.test', 'data/sonicyouth-daydreamnation.cod'))

        basic_disc = model.DbDisc.from_musicbrainz_disc(MusicbrainzDiscDummy(
            [(183, 31377), (31560, 17080), (48640, 34688), (83328, 31540),
             (114868, 17152), (132020, 34018), (166038, 19730), (185768, 12130),
             (197898, 22422), (220320, 20963), (241283, 14147), (255430, 63503)],
            disc_id = d.disc_id))

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
            resource_string('codplayer.test', 'data/' + testfile), 'testId')

    def test_plain_disc(self):
        """Addis Black Widow - Wait in Summer (single):
        Nothing fancy, just two tracks with regular separation.
        """

        d = model.DbDisc.from_musicbrainz_disc(MusicbrainzDiscDummy(
            [(150, 17207), (17357, 14263)]))

        tocd = self.read_toc('abw-waitinsummer.toc')

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

        d = model.DbDisc.from_musicbrainz_disc(MusicbrainzDiscDummy(
            [(17285, 15590), (32875, 15987), (48862, 16303),
             (65165, 17807), (82972, 18808), (101780, 18010),
             (119790, 16030), (135820, 18635), (154455, 16727),
             (171182, 18710), (189892, 15293), (205185, 15992),
             (221177, 19503), (240680, 21557)]))

        tocd = self.read_toc('kylie-lightyears.toc')

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
        d = model.DbDisc.from_musicbrainz_disc(MusicbrainzDiscDummy(
            [(150, 14435), (14585, 14556), (29141, 14900), (44041, 14266),
             (58307, 22380), (80687, 15701), (96388, 15820), (112208, 15840),
             (128048, 15086), (143134, 25354)]))

        tocd = self.read_toc('cocteautwins-heavenorlasvegas.toc')
        toc.merge_full_toc(d, tocd)

        self.assertEqual(d.title, 'HEAVEN OR LAS VEGAS')
        self.assertEqual(d.artist, 'THE COCTEAU TWINS')

        t = d.tracks[9]
        self.assertEqual(t.title, 'FROU-FROU FOXES IN MIDSUMMER FIRES')
        self.assertEqual(t.artist, None)


    def test_do_not_overwrite_track_info_with_cdtext(self):
        d = model.DbDisc.from_musicbrainz_disc(MusicbrainzDiscDummy(
            [(150, 14435), (14585, 14556), (29141, 14900), (44041, 14266),
             (58307, 22380), (80687, 15701), (96388, 15820), (112208, 15840),
             (128048, 15086), (143134, 25354)]))

        # Set some TOC info
        d.title = 'foo'
        d.artist = 'bar'
        d.tracks[0].title = 'gazonk'
        d.tracks[0].artist = 'bar'

        tocd = self.read_toc('cocteautwins-heavenorlasvegas.toc')
        toc.merge_full_toc(d, tocd)

        self.assertEqual(d.title, 'foo')
        self.assertEqual(d.artist, 'bar')

        t = d.tracks[0]
        self.assertEqual(t.title, 'gazonk')
        self.assertEqual(t.artist, 'bar')


