# codplayer - test the disc module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest

from .. import model

class TestMSF(unittest.TestCase):
    def test_1s(self):
        s = model.PCM.msf_to_samples('00:01:00')
        self.assertEquals(s, model.PCM.rate)

    def test_full(self):
        s = model.PCM.msf_to_samples('08:17:74')
        self.assertEquals(s, (8 * 60 + 17) * model.PCM.rate + 74 * 588)


class TestDiscFromToc(unittest.TestCase):
    def test_no_tracks(self):
        toc = '''
CD_DA
'''
        with self.assertRaises(model.DiscInfoError):
            model.Disc.from_toc(toc, 'testId')


    def test_catalog_and_basic_track(self):
        # Test ignoring data tracks too
        toc = '''
CD_DA

CATALOG "0123456789012"

TRACK MODE1
DATAFILE "foo.dat"

TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53
'''
        d = model.Disc.from_toc(toc, 'testId')

        self.assertEqual(d.disc_id, 'testId')

        self.assertEqual(d.catalog, "0123456789012")
        self.assertEqual(d.data_file_name, "data.cdr")
        self.assertEqual(d.data_file_format, model.RAW_CD)
        self.assertEqual(d.data_sample_format, model.PCM)


        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_samples('02:54:53'))
        

    def test_multiple_tracks(self):
        toc = '''
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
        d = model.Disc.from_toc(toc, 'testId')

        self.assertEqual(d.catalog, None)
        self.assertEqual(d.data_file_name, "data.cdr")
        self.assertEqual(d.data_file_format, model.RAW_CD)
        self.assertEqual(d.data_sample_format, model.PCM)


        self.assertEqual(len(d.tracks), 3)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_samples('02:54:53'))

        t = d.tracks[1]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset, model.PCM.msf_to_samples('02:54:53'))
        self.assertEqual(t.length, model.PCM.msf_to_samples('03:29:65'))

        t = d.tracks[2]
        self.assertEqual(t.number, 3)
        self.assertEqual(t.file_offset, model.PCM.msf_to_samples('06:24:43'))
        self.assertEqual(t.length, model.PCM.msf_to_samples('03:36:67'))
        

    def test_ignore_comments(self):
        # Test ignoring data tracks too
        toc = '''
// CATALOG "0123456789012"

TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53 // foo bar

 // TRACK AUDIO
  // TWO_CHANNEL_AUDIO
// FILE "data.cdr" 02:54:53 03:29:65
'''
        d = model.Disc.from_toc(toc, 'testId')

        self.assertIsNone(d.catalog)

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_samples('02:54:53'))
        


    def test_pregap_silence(self):
        # Hidden track on Kylie Minogue, Light Years.  This
        # cdrdao-based code wouldn't be able to find and play it...
        toc = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
SILENCE 03:48:35
FILE "data.cdr" 0 03:27:10
START 03:48:35
'''
        d = model.Disc.from_toc(toc, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_samples('03:27:10'))
        self.assertEqual(t.pregap_offset, model.PCM.msf_to_samples('03:48:35'))
        self.assertEqual(t.pregap_silence, model.PCM.msf_to_samples('03:48:35'))


    def test_start_index(self):
        toc = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53
START 00:01:22
INDEX 00:03:11
INDEX 00:05:00
'''
        d = model.Disc.from_toc(toc, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_samples('02:54:53'))
        self.assertEqual(t.pregap_offset, model.PCM.msf_to_samples('00:01:22'))

        # Indexes will have been translated from relative to pregap to
        # relative to track start

        self.assertEqual(len(t.index), 2)
        self.assertEqual(t.index[0], model.PCM.msf_to_samples('00:04:33'))
        self.assertEqual(t.index[1], model.PCM.msf_to_samples('00:06:22'))



    def test_fail_on_cdtext(self):
        toc = '''
CD_DA

CD_TEXT {
    LANGUAGE_MAP {
      0 : EN
    }

    LANGUAGE 0 {
      TITLE "CD Title"
      PERFORMER "Performer"
      DISC_ID "XY12345"
      UPC_EAN ""
    }
}
'''
        with self.assertRaises(model.DiscInfoError):
            model.Disc.from_toc(toc, 'testId')


    def test_track_isrc(self):
        toc = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
ISRC "GBAYE0000351"
FILE "data.cdr" 0 03:27:10
'''
        d = model.Disc.from_toc(toc, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_samples('03:27:10'))
        self.assertEqual(t.isrc, "GBAYE0000351")
            

# Helper object to avoid dragging in musicbrainz2 just for testing
class MusicbrainzDiscDummy(object):
    def __init__(self, *tracks):
        self.tracks = tracks

    def getId(self):
        return 'testId'

    def getTracks(self):
        return self.tracks
    

class TestDiscFromMusicbrainz(unittest.TestCase):
    def test_notracks(self):
        mb_d = MusicbrainzDiscDummy()

        with self.assertRaises(model.DiscInfoError):
            model.Disc.from_musicbrainz_disc(mb_d)


    def test_tracks(self):
        mb_d = MusicbrainzDiscDummy(
            (150, 34630),
            (34780, 37470),
            (72250, 9037))

        d = model.Disc.from_musicbrainz_disc(mb_d, 'test.cdr')

        self.assertEqual(d.disc_id, 'testId')

        self.assertEqual(d.catalog, None)
        self.assertEqual(d.data_file_name, "test.cdr")
        self.assertEqual(d.data_file_format, model.RAW_CD)
        self.assertEqual(d.data_sample_format, model.PCM)

        self.assertEqual(len(d.tracks), 3)

        # The pregap will not be read by cdrdao

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length,
                         34630 * model.PCM.samples_per_frame)

        t = d.tracks[1]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset,
                         (34780 - 150) * model.PCM.samples_per_frame)
        self.assertEqual(t.length,
                         37470 * model.PCM.samples_per_frame)

        t = d.tracks[2]
        self.assertEqual(t.number, 3)
        self.assertEqual(t.file_offset,
                         (72250 - 150) * model.PCM.samples_per_frame)
        self.assertEqual(t.length,
                         9037 * model.PCM.samples_per_frame)
