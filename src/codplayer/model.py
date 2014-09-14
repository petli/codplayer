# codplayer - data model for discs and tracks
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes representing discs and tracks.

The unit of time in all objects is one audio frame, i.e. one sample
for each channel.

Confusingly, the CD format has it's own definition of frame.  There
are 75 CD frames per second, each consisting of 588 audio frames.
"""

from musicbrainzngs import mbxml

from . import serialize

# Basic data formats


class PCM:
    channels = 2
    bytes_per_sample = 2
    bytes_per_frame = 4
    rate = 44100
    big_endian = True

    cd_frames_per_second = 75
    audio_frames_per_cd_frame = 588

    @classmethod
    def msf_to_frames(cls, msf):
        """Translate an MM:SS:FF to number of PCM audio frames."""

        d = msf.split(':')
        if len(d) != 3:
            raise ValueError(msf)

        m = int(d[0], 10)
        s = int(d[1], 10)
        f = int(d[2], 10)

        return (((m * 60) + s) * 75 + f) * cls.audio_frames_per_cd_frame



class RAW_CD:
    file_suffix = '.cdr'


# Various exceptions

class DiscInfoError(Exception):
    pass

    
#
# Base data classes containing the basic attributes that are used both
# in the database and in communication with external components
#

class Disc(serialize.Serializable):

    MAPPING = (
        serialize.Attr('disc_id', str),
        serialize.Attr('mb_id', str, optional = True),
        serialize.Attr('cover_mb_id', str, optional = True),
        serialize.Attr('catalog', serialize.str_unicode, optional = True),
        serialize.Attr('title', serialize.str_unicode, optional = True),
        serialize.Attr('artist', serialize.str_unicode, optional = True),
        serialize.Attr('barcode', serialize.str_unicode, optional = True),
        serialize.Attr('date', serialize.str_unicode, optional = True),

        # tracks mapping is added by the subclasses
        )

    def __init__(self):
        self.disc_id = None
        self.mb_id = None
        self.cover_mb_id = None
        
        self.tracks = []
        
        # Information we might get from the TOC, or failing that MusicBrainz
        self.catalog = None
        self.title = None
        self.artist = None

        # Additional information we might get from MusicBrainz (not
        # every possible morsel, but what might be useful to keep locally)
        self.barcode = None
        self.date = None

    def __str__(self):
        return u'{self.disc_id}: {self.artist}/{self.title}'.format(self = self).encode('utf-8')


class Track(serialize.Serializable):
    MAPPING = (
        serialize.Attr('isrc', serialize.str_unicode, optional = True),
        serialize.Attr('title', serialize.str_unicode, optional = True),
        serialize.Attr('artist', serialize.str_unicode, optional = True),

        # Length fields are added by the subclasses

        # Edit fields
        serialize.Attr('skip', bool, optional = True, default = False),
        serialize.Attr('pause_after', bool, optional = True, default = False),
        )

    def __init__(self):
        self.number = 0
        self.length = 0

        # Where index switch from 0 to 1
        self.pregap_offset = 0

        # Any additional indices
        self.index = []

        # Information we might get from the TOC, or failing that MusicBrainz
        self.isrc = None
        self.title = None
        self.artist = None

        # Edit information
        self.skip = False
        self.pause_after = False


#
# Database versions of disc and track classes
#

class DbTrack(Track):
    """Represents one track on a disc and its offsets and indices.
    All time values are in frames.
    """

    MAPPING = Track.MAPPING + (
        serialize.Attr('number', int),
        serialize.Attr('length', int),
        serialize.Attr('pregap_offset', int),
        serialize.Attr('index', list_type = int),
        serialize.Attr('file_offset', int),
        serialize.Attr('file_length', int),
        serialize.Attr('pregap_silence', int),
        )

    MUTABLE_ATTRS = (
        'isrc',
        'title',
        'artist',
        'skip',
        'pause_after',
        )

    def __init__(self):
        super(DbTrack, self).__init__()
        
        self.file_offset = 0
        self.file_length = 0

        # If part or all of the pregap isn't contained in the data
        # file at all
        self.pregap_silence = 0
        

class DbDisc(Disc):
    """Represents a CD, consisting of a number of tracks.  All time
    values are in frames.
    """

    MAPPING = Disc.MAPPING + (
        serialize.Attr('tracks', list_type = DbTrack),

        # Process flags: optional to be backward-compatible with
        # pre-1.0 rips
        serialize.Attr('rip', bool, optional = True, default = False),
        serialize.Attr('toc', bool, optional = True, default = False),

        serialize.Attr('data_file_name', serialize.str_unicode),
        serialize.Attr('data_file_format', enum = (RAW_CD, )),
        serialize.Attr('audio_format', enum = (PCM, )),
        )

    MUTABLE_ATTRS = (
        'mb_id',
        'cover_mb_id',
        'catalog', 
        'title',
        'artist',
        'barcode',
        'date',
        )

    def __init__(self):
        super(DbDisc, self).__init__()
        
        self.rip = False
        self.toc = False
        self.data_file_name = None
        self.data_file_format = None
        self.audio_format = None


    def add_track(self, track):
        self.tracks.append(track)
        track.number = len(self.tracks)




    @classmethod
    def from_musicbrainz_disc(cls, mb_disc, filename = None):
        """Translate a L{musicbrainz2.model.Disc} into a L{DbDisc}.
        This will just be a basic TOC with start/length for each track, but
        is sufficient for playing a raw data file.

        @param mb_disc: a L{musicbrainz2.model.Disc} object

        @param filename: the filename for the data file that is
        expected to be written by the ripping process.

        @return: a L{DbDisc} object.
        """

        tracks = mb_disc.getTracks()

        # Make sure we have any tracks
        if not tracks:
            raise DiscInfoError('no audio tracks on disc')

        disc = cls()
        disc.disc_id = mb_disc.getId()


        if filename is not None:
            disc.data_file_name = filename

            if filename.endswith(RAW_CD.file_suffix):
                disc.data_file_format = RAW_CD
                disc.audio_format = PCM
            else:
                raise DiscInfoError('unknown file format: "%s"'
                                    % filename)

        for start, length in tracks:
            # libdiscid adds a standard pregap of 2s to the track
            # start offset, so remove that to get to the real start
            # of the track.
            start -= 2 * PCM.cd_frames_per_second

            track = DbTrack()
            track.file_offset = start * PCM.audio_frames_per_cd_frame
            track.length = length * PCM.audio_frames_per_cd_frame
            track.file_length = track.length
            disc.add_track(track)

        return disc
    

    def get_disc_file_size_frames(self):
        """Return expected length of the file representing this disc,
        in frames.  This assumes that the disc tracks have not been shuffled.
        """
        if self.tracks:
            t = self.tracks[-1]
            return t.file_offset + t.file_length
        else:
            return 0

    def get_disc_file_size_bytes(self):
        """Return expected length of the file representing this disc,
        in bytes.  This assumes that the disc tracks have not been shuffled.
        """
        return self.get_disc_file_size_frames() * self.audio_format.bytes_per_frame



#
# External views of the database objects
#

class ExtTrack(Track):
    """External view of a track, hiding internal details and exposing
    all lengths as whole seconds.
    """

    MAPPING = Track.MAPPING + (
        serialize.Attr('number', int, optional = True),
        serialize.Attr('length', int, optional = True),
        serialize.Attr('pregap_offset', int, optional = True),
        serialize.Attr('index', list_type = int, optional = True),
        )
    
    def __init__(self, track = None, disc = None):
        super(ExtTrack, self).__init__()
        
        if track:
            assert isinstance(track, DbTrack)
            assert isinstance(disc, DbDisc)
            
            self.number = track.number
            self.length = int(track.length / disc.audio_format.rate)
            self.pregap_offset = int(track.pregap_offset / disc.audio_format.rate)
            self.index = [int(i / disc.audio_format.rate) for i in track.index]
            self.isrc = track.isrc
            self.title = track.title
            self.artist = track.artist
            self.skip = track.skip
            self.pause_after = track.pause_after


class ExtDisc(Disc):
    """External view of a Disc, hiding internal details and exposing
    all lengths as whole seconds.
    """

    MAPPING = Disc.MAPPING + (
        serialize.Attr('tracks', list_type = ExtTrack),
        )

    def __init__(self, disc = None):
        super(ExtDisc, self).__init__()
        
        if disc:
            assert isinstance(disc, DbDisc)
            self.disc_id = disc.disc_id
            self.mb_id = disc.mb_id
            self.cover_mb_id = disc.cover_mb_id
            self.tracks = [ExtTrack(t, disc) for t in disc.tracks]
            self.catalog = disc.catalog
            self.title = disc.title
            self.artist = disc.artist
            self.barcode = disc.barcode
            self.date = disc.date


    @classmethod
    def get_from_mb_xml(cls, xml, disc_id):
        """Parse Musicbrainz XML for a given disc_id. The XML should
        have been returned from a
        "/ws/2/discid/DISC_ID?inc=recordings artist" query.

        This returns a list of matching discs.
        """

        return cls.get_from_mb_dict(mbxml.parse_message(xml), disc_id)

    @classmethod
    def get_from_mb_dict(cls, mb_dict, disc_id):
        """Parse a Musicbrainz dict for a given disc_id. The dict should
        have been returned from a
        "/ws/2/discid/DISC_ID?inc=recordings artist" query.

        This returns a list of matching discs.
        """

        discs = []

        # Dig down until we find a medium (== disc) matching the
        # provided disc_id

        if mb_dict.has_key('disc'):
            for release in mb_dict['disc']['release-list']:
                for medium in release['medium-list']:
                    for mb_disc_id in medium['disc-list']:
                        if disc_id == mb_disc_id['id']:
                            add_mb_ext_disc(discs, cls, disc_id, release, medium)

        elif mb_dict.has_key('cdstub'):
            add_cdstub_ext_disc(discs, cls, disc_id, mb_dict['cdstub'])

        return discs

#
# Musicbrainz helper functions
#
    
def add_mb_ext_disc(discs, cls, disc_id, release, medium):
    disc = cls()
    disc.disc_id = disc_id
    disc.mb_id = release['id']

    if len(release['medium-list']) == 1:
        disc.title = release['title']
    else:
        disc.title = u'{0} (disc {1})'.format(release['title'], medium['position'])

    disc.artist = release['artist-credit-phrase']
    disc.date = release.get('date')
    disc.barcode = release.get('barcode')

    disc._cover_count = int(release['cover-art-archive']['count'])
    disc.cover_mb_id = disc.mb_id if disc._cover_count > 0 else None

    for mbtrack in medium['track-list']:
        track = ExtTrack()
        track.number = int(mbtrack['position'])
        track.length = int(mbtrack['length']) / 1000
        track.title = mbtrack['recording']['title']
        track.artist = mbtrack['recording']['artist-credit-phrase']

        disc.tracks.append(track)

    disc.tracks.sort(lambda a, b: cmp(a.number, b.number))

    # If an identical disc is already in the list, don't add it
    for other in discs:
        if same_disc_title_and_artist(disc, other):
            # Keep the oldest date to get something closer to the
            # original release.
            if (disc.date is not None
                and (other.date is None or disc.date < other.date)):
                other.date = disc.date
                other.mb_id = disc.mb_id

            # Keep track of the release with the most artworks
            if (disc.cover_mb_id is not None
                and (other.cover_mb_id is None
                     or other._cover_count < disc._cover_count)):
                other.cover_mb_id = disc.cover_mb_id
                other._cover_count = disc._cover_count

            # Nothing to add here
            return

    # This was the first time we saw this disc
    discs.append(disc)


def same_disc_title_and_artist(disc, other):
    if disc.title != other.title: return False
    if disc.artist != other.artist: return False

    if len(disc.tracks) != len(other.tracks): return False

    for dt, ot in zip(disc.tracks, other.tracks):
        if dt.title != ot.title: return False
        if dt.artist != ot.artist: return False

    return True

def add_cdstub_ext_disc(discs, cls, disc_id, cdstub):
    disc = cls()
    disc.disc_id = disc_id
    disc.title = cdstub['title']
    disc.artist = cdstub['artist']

    for mb_track in cdstub['track-list']:
        track = ExtTrack()
        track.number = len(disc.tracks) + 1
        track.title = mb_track['title']
        track.length = int(mb_track['length']) / 1000
        disc.tracks.append(track)
        
    discs.append(disc)
    
