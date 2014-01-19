# codplayer - test the model module
# -*- coding: utf-8 -*-
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import os

from .. import model
from .. import serialize

class TestMSF(unittest.TestCase):
    def test_1s(self):
        s = model.PCM.msf_to_frames('00:01:00')
        self.assertEquals(s, model.PCM.rate)

    def test_full(self):
        s = model.PCM.msf_to_frames('08:17:74')
        self.assertEquals(s, (8 * 60 + 17) * model.PCM.rate + 74 * 588)


class TestDiscFromToc(unittest.TestCase):
    def test_no_tracks(self):
        toc = '''
CD_DA
'''
        with self.assertRaises(model.DiscInfoError):
            model.DbDisc.from_toc(toc, 'testId')


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
        d = model.DbDisc.from_toc(toc, 'testId')

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
        d = model.DbDisc.from_toc(toc, 'testId')

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
        toc = '''
// CATALOG "0123456789012"

TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53 // foo bar

 // TRACK AUDIO
  // TWO_CHANNEL_AUDIO
// FILE "data.cdr" 02:54:53 03:29:65
'''
        d = model.DbDisc.from_toc(toc, 'testId')

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
        toc = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
SILENCE 03:48:35
FILE "data.cdr" 0 03:27:10
START 03:48:35
'''
        d = model.DbDisc.from_toc(toc, 'testId')

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
        toc = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
FILE "data.cdr" 0 02:54:53
START 00:01:22
INDEX 00:03:11
INDEX 00:05:00
'''
        d = model.DbDisc.from_toc(toc, 'testId')

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
        toc = '''
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

        d = model.DbDisc.from_toc(toc, 'testId')

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
        toc = '''
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

        d = model.DbDisc.from_toc(toc, 'testId')

        self.assertEqual(len(d.tracks), 1)
        self.assertEqual(d.data_file_name, "data.cdr")

        self.assertEqual(d.title, 'Disc title')
        self.assertEqual(d.artist, 'Disc artist')

        t = d.tracks[0]
        self.assertEqual(t.title, 'Title track 1')
        self.assertEqual(t.artist, 'Artist track 1')
        self.assertEqual(t.file_offset, 0)


    def test_track_isrc(self):
        toc = '''
TRACK AUDIO
TWO_CHANNEL_AUDIO
ISRC "GBAYE0000351"
FILE "data.cdr" 0 03:27:10
'''
        d = model.DbDisc.from_toc(toc, 'testId')

        self.assertEqual(len(d.tracks), 1)

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length, model.PCM.msf_to_frames('03:27:10'))
        self.assertEqual(t.length, t.file_length)
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
            model.DbDisc.from_musicbrainz_disc(mb_d)


    def test_tracks(self):
        mb_d = MusicbrainzDiscDummy(
            (150, 34630),
            (34780, 37470),
            (72250, 9037))

        d = model.DbDisc.from_musicbrainz_disc(mb_d, 'test.cdr')

        self.assertEqual(d.disc_id, 'testId')

        self.assertEqual(d.catalog, None)
        self.assertEqual(d.data_file_name, "test.cdr")
        self.assertEqual(d.data_file_format, model.RAW_CD)
        self.assertEqual(d.audio_format, model.PCM)

        self.assertEqual(len(d.tracks), 3)

        # The pregap will not be read by cdrdao

        t = d.tracks[0]
        self.assertEqual(t.number, 1)
        self.assertEqual(t.file_offset, 0)
        self.assertEqual(t.length,
                         34630 * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, t.file_length)

        t = d.tracks[1]
        self.assertEqual(t.number, 2)
        self.assertEqual(t.file_offset,
                         (34780 - 150) * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length,
                         37470 * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, t.file_length)

        t = d.tracks[2]
        self.assertEqual(t.number, 3)
        self.assertEqual(t.file_offset,
                         (72250 - 150) * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length,
                         9037 * model.PCM.audio_frames_per_cd_frame)
        self.assertEqual(t.length, t.file_length)


class TestDiscFromJSON(unittest.TestCase):
    def test_ext_disc(self):
        raw = '''
{
  "artist": "Brainpool", 
  "barcode": "4711", 
  "catalog": "4712", 
  "disc_id": "Fy3nZdEhBmXzkiolzR08Xk5rPQ4-", 
  "date": "2010-10-10",
  "mb_id": "fake-id",
  "title": "We Aimed To Please (Best Of Brainpool Vol.1)", 
  "tracks": [
    {
      "artist": "Brainpool", 
      "index": [190], 
      "isrc": "SEWNV0500101", 
      "length": 195, 
      "number": 1, 
      "pregap_offset": 0, 
      "title": "At School"
    }
  ]
}
'''
        obj = serialize.load_jsons(model.ExtDisc, raw)

        self.assertEqual(obj.artist, 'Brainpool')
        self.assertEqual(obj.barcode, '4711')
        self.assertEqual(obj.catalog, '4712')
        self.assertEqual(obj.disc_id, 'Fy3nZdEhBmXzkiolzR08Xk5rPQ4-')
        self.assertEqual(obj.mb_id, 'fake-id')
        self.assertEqual(obj.date, '2010-10-10')
        self.assertEqual(obj.title, 'We Aimed To Please (Best Of Brainpool Vol.1)')
        
        self.assertEqual(len(obj.tracks), 1)

        t = obj.tracks[0]
        self.assertEqual(t.artist, 'Brainpool')
        self.assertListEqual(t.index, [190])
        self.assertEqual(t.isrc, 'SEWNV0500101')
        self.assertEqual(t.length, 195)
        self.assertEqual(t.number, 1)
        self.assertEqual(t.pregap_offset, 0)
        self.assertEqual(t.title, 'At School')
        

    def test_db_disc(self):
        raw = '''
{
  "artist": "Brainpool", 
  "audio_format": "PCM",
  "barcode": "4711",
  "catalog": "4712", 
  "data_file_format": "RAW_CD",
  "data_file_name": "172de765.cdr",
  "disc_id": "Fy3nZdEhBmXzkiolzR08Xk5rPQ4-",
  "date": "2010-10-10", 
  "title": "We Aimed To Please (Best Of Brainpool Vol.1)", 
  "tracks": [
    {
      "artist": "Brainpool",
      "file_length": 8599500,
      "file_offset": 0,
      "index": [8379000], 
      "isrc": "SEWNV0500101", 
      "length": 8599500, 
      "number": 1, 
      "pregap_offset": 0, 
      "pregap_silence": 0, 
      "title": "At School"
    }
  ]
}
'''
        obj = serialize.load_jsons(model.DbDisc, raw)

        self.assertEqual(obj.artist, 'Brainpool')
        self.assertIs(obj.audio_format, model.PCM)
        self.assertEqual(obj.barcode, '4711')
        self.assertEqual(obj.catalog, '4712')
        self.assertIs(obj.data_file_format, model.RAW_CD)
        self.assertEqual(obj.data_file_name, '172de765.cdr')
        self.assertEqual(obj.disc_id, 'Fy3nZdEhBmXzkiolzR08Xk5rPQ4-')
        self.assertEqual(obj.date, '2010-10-10')
        self.assertIsNone(obj.mb_id)
        self.assertEqual(obj.title, 'We Aimed To Please (Best Of Brainpool Vol.1)')
        
        self.assertEqual(len(obj.tracks), 1)

        t = obj.tracks[0]
        self.assertEqual(t.artist, 'Brainpool')
        self.assertEqual(t.file_length, 8599500)
        self.assertEqual(t.file_offset, 0)
        self.assertListEqual(t.index, [8379000])
        self.assertEqual(t.isrc, 'SEWNV0500101')
        self.assertEqual(t.length, 8599500)
        self.assertEqual(t.number, 1)
        self.assertEqual(t.pregap_offset, 0)
        self.assertEqual(t.pregap_silence, 0)
        self.assertEqual(t.title, 'At School')


class TestMusicbrainz(unittest.TestCase):
    def get_test_xml(self, name):
        path = os.path.join(
            os.path.dirname(__file__),
            'data',
            name)
        
        return open(path, 'rt').read()

    def test_discset_compilation(self):
        xml = self.get_test_xml('discset-compilation.xml')

        # Disc two of a very good disco compilation
        discs = model.ExtDisc.get_from_mb_xml(xml, '3xX9wXAggfDzwq32XenV9CFGsm0-')

        self.assertEqual(len(discs), 1)
        d = discs[0]
        
        self.assertEqual(d.disc_id, '3xX9wXAggfDzwq32XenV9CFGsm0-')
        self.assertEqual(d.mb_id, u'08c4ce0e-9c09-4057-b9ca-3d9acb20bf1c')
        self.assertEqual(d.title, u'Disco Discharge: Classic Disco (disc 2)')
        self.assertEqual(d.artist, u'Various Artists')
        self.assertEqual(d.date, u'2009')

        self.assertEqual(len(d.tracks), 10)
        t = d.tracks[6]

        self.assertEqual(t.number, 7)
        self.assertEqual(t.length, 618)
        self.assertEqual(t.title, u'Look for Love')
        self.assertEqual(t.artist, u'Cerrone')
        
    def test_many_releases(self):
        xml = self.get_test_xml('many-releases.xml')

        # Blonde on Blonde has been released many, many times... 
        discs = model.ExtDisc.get_from_mb_xml(xml, 'CfMonbWEmkO6tDj8k0KBoRXrH6M-')

        # But we expect that the titles of all of them are the same,
        # so there should just be one left
        self.assertEqual(len(discs), 1)
        d = discs[0]
        
        self.assertEqual(d.disc_id, 'CfMonbWEmkO6tDj8k0KBoRXrH6M-')
        self.assertEqual(d.mb_id, u'4d894f37-ca03-38ff-bad2-ef1aaa5ea9c0')
        self.assertEqual(d.title, u'Blonde on Blonde')
        self.assertEqual(d.artist, u'Bob Dylan')
        self.assertEqual(d.date, u'1982-05')

        self.assertEqual(len(d.tracks), 14)
        t = d.tracks[2]

        self.assertEqual(t.number, 3)
        self.assertEqual(t.length, 454)
        self.assertEqual(t.title, u'Visions of Johanna')
        self.assertEqual(t.artist, u'Bob Dylan')
        
    def test_different_titles(self):
        xml = self.get_test_xml('different-titles.xml')

        # Behaviour is my desert island disc.  And the remaster has a
        # slightly different title.
        discs = model.ExtDisc.get_from_mb_xml(xml, 'GVrNYbjD87B.vpShA1rZHbw3WQo-')

        self.assertEqual(len(discs), 2)

        if discs[0].title == 'Behaviour':
            orig = discs[0]
            remaster = discs[1]
        else:
            orig = discs[1]
            remaster = discs[0]
            
        self.assertEqual(orig.disc_id, 'GVrNYbjD87B.vpShA1rZHbw3WQo-')
        self.assertEqual(orig.mb_id, u'30a9bbd6-e456-3478-9a35-1cf958cf9637')
        self.assertEqual(orig.title, u'Behaviour')
        self.assertEqual(orig.artist, u'Pet Shop Boys')
        self.assertEqual(orig.date, u'1990-10-22')

        self.assertEqual(remaster.disc_id, 'GVrNYbjD87B.vpShA1rZHbw3WQo-')
        self.assertEqual(remaster.mb_id, u'd7762dcc-90cc-4c03-9008-624457c40010')
        self.assertEqual(remaster.title, u'Behaviour / Further Listening 1990-1991 (disc 1)')
        self.assertEqual(remaster.artist, u'Pet Shop Boys')
        self.assertEqual(remaster.date, u'2001-06-04')

    def test_cdstub(self):
        xml = self.get_test_xml('cdstub.xml')

        # This one is Swedish, despite the artist name
        discs = model.ExtDisc.get_from_mb_xml(xml, 'umw3uGXn_h78p6weU1v48WDGe0U-')

        self.assertEqual(len(discs), 1)
        d = discs[0]
        
        self.assertEqual(d.disc_id, 'umw3uGXn_h78p6weU1v48WDGe0U-')
        self.assertIsNone(d.mb_id)
        self.assertEqual(d.title, u'Ljudet Av Tiden Som Går')
        self.assertEqual(d.artist, u'Mauro Scocco')
        self.assertIsNone(d.date)

        self.assertEqual(len(d.tracks), 11)
        t = d.tracks[2]

        self.assertEqual(t.number, 3)
        self.assertEqual(t.length, 234)
        self.assertEqual(t.title, u'Taxi')
        self.assertEqual(t.artist, None)
