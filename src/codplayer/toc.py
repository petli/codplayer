# codplayer - data model for discs and tracks
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Functions for turning cdrdao TOCs into model.DbDisc objects,
including merging with the basic track start/length TOC from
libdiscid.
"""

import re

from . import model

class TOCError(Exception):
    pass


def read_toc(path, disc_id):
    """Read and parse a TOC file generated by cdrdao into a DbDisc
    instance.

    @param path: path to the TOC file
    @param disc_id: a Musicbrainz disc ID (not calculated from the TOC)

    @return: A L{DbDisc} object.

    @raise TOCError: if the TOC can't be read or parsed.
    """

    try:
        f = open(path, 'rt')
        toc_data = f.read(50000) # keep it sane
        f.close()
    except IOError as e:
        raise TOCError('error reading {0}: {1}'.format(path, e))

    return parse_toc(toc_data, disc_id)


def merge_basic_toc(old_disc, toc_disc):
    """Merge a basic TOC into an existing model.DbDisc.

    This is only used when encountering an a disc in the database that
    has been ripped with the cdrdao-only method, and ensures that any
    track information added later is retained while still resetting
    the track offsets and length to the basic information, discarding
    the not-that-reliable information that we got from cdrdao when
    both ripping audio and TOC the first time.  This is only temporary,
    as a full proper TOC will be read next, but ensures a consistent disc
    state during the process.
    """

    assert toc_disc.disc_id == old_disc.disc_id
    assert len(toc_disc.tracks) == len(old_disc.tracks)

    for ot, tt in zip(old_disc.tracks, toc_disc.tracks):
        ot.file_offset = tt.file_offset
        ot.length = ot.file_length = tt.file_length
        ot.pregap_offset = ot.pregap_silence = 0
        ot.index = []


def merge_full_toc(old_disc, toc_disc):
    """Merges the TOC read by cdrdao into an existing model.DbDisc.

    The reason that this is needed is that we can't trust the file
    offsets fully when just reading a TOC with cdrdao, so we're
    instead using the offsets from the basic TOC already present in
    the file.  Together with the good index information we get from
    cdrdao when just reading a TOC and not ripping a disc at the same
    time, we get something that's as close as possible to the actual
    CD.

    This method also tries to discover "hidden" tracks before the
    first one, and adds them as track 0.  It is then up to you if you
    want to keep them or silence them.

    """

    assert toc_disc.disc_id == old_disc.disc_id
    assert len(toc_disc.tracks) == len(old_disc.tracks)

    # Update general disc info
    old_disc.catalog = old_disc.catalog or toc_disc.catalog
    old_disc.artist = old_disc.artist or toc_disc.artist
    old_disc.title = old_disc.title or toc_disc.title
    old_disc.barcode = old_disc.barcode or toc_disc.barcode


    # Detect "hidden" first tracks.  Anything more than 2s is
    # suspicious.
    hidden = None
    ot = old_disc.tracks[0]
    tt = toc_disc.tracks[0]
    if ot.file_offset > 2 * model.PCM.rate:
        hidden = model.DbTrack()
        hidden.file_offset = 0
        hidden.file_length = hidden.length = ot.file_offset

        # The TOC might announce the track as silence, so nuke that
        tt.pregap_silence = 0
        tt.pregap_offset = 0
        tt.length = tt.file_length

    # Then process tracks normally
    prev = None
    for ot, tt in zip(old_disc.tracks, toc_disc.tracks):
        # Move pregap into the track
        ot.pregap_offset = tt.pregap_offset
        ot.pregap_silence = tt.pregap_silence
        ot.file_offset -= tt.pregap_offset
        ot.length = tt.length
        ot.file_length = tt.file_length
        ot.index = list(tt.index)

        ot.isrc = ot.isrc or tt.isrc
        ot.artist = ot.artist or tt.artist
        ot.title = ot.title or tt.title

    if hidden:
        old_disc.tracks.insert(0, hidden)


def parse_toc(toc, disc_id):
    """Parse a TOC generated by cdrdao into a DbDisc instance.

    This is not a full parse of all varieties that cdrdao itself
    allows, as this function is only intended to be used on TOCs
    generated by cdrdao itself.

    @param toc: a cdrdao TOC as a string
    @param disc_id: a Musicbrainz disc ID (not calculated from the TOC)

    @return: A L{DbDisc} object.

    @raise TOCError: if the TOC can't be parsed.
    """

    disc = model.DbDisc()
    disc.disc_id = disc_id

    track = None
    cd_text = CDText()

    iter_toc = iter_toc_lines(toc)
    for line in iter_toc:

        # Don't bother about disc flags
        if line in ('CD_DA', 'CD_ROM', 'CD_ROM_XA'):
            pass

        elif line.startswith('CATALOG '):
            disc.catalog = get_toc_string_arg(line)

        # Start of a new track
        elif line.startswith('TRACK '):

            if track is not None:
                disc.add_track(track)

            if line == 'TRACK AUDIO':
                track = model.DbTrack()
            else:
                # Just skip non-audio tracks
                track = None

        # Ignore some track flags that don't matter to us
        elif line in ('TWO_CHANNEL_AUDIO',
                      'COPY', 'NO COPY',
                      'PRE_EMPHASIS', 'NO PRE_EMPHASIS'):
            pass

        # Anyone ever seen one of these discs?
        elif line == 'FOUR_CHANNEL_AUDIO':
            raise TOCError('no support for four-channel audio')

        # Implement CD_TEXT later
        elif line.startswith('CD_TEXT '):
            info = cd_text.parse(line[7:], iter_toc, track is None)
            if info:
                if track is None:
                    disc.artist = info.get('artist')
                    disc.title = info.get('title')
                else:
                    track.artist = info.get('artist')
                    track.title = info.get('title')


        # Pick up the offsets within the data file
        elif line.startswith('FILE '):
            filename = get_toc_string_arg(line)

            if disc.data_file_name is None:
                disc.data_file_name = filename

                if filename.endswith(model.RAW_CD.file_suffix):
                    disc.data_file_format = model.RAW_CD
                    disc.audio_format = model.PCM
                else:
                    raise TOCError('unknown file format: "%s"'
                                        % filename)

            elif disc.data_file_name != filename:
                raise TOCError('expected filename "%s", got "%s"'
                                    % (disc.data_file_name, filename))


            p = line.split()

            # Just assume the last two are either 0 or an MSF
            if len(p) < 4:
                raise TOCError('missing offsets in file: %s' % line)

            offset = p[-2]
            length = p[-1]

            if offset == '0':
                track.file_offset = 0
            else:
                try:
                    track.file_offset = model.PCM.msf_to_frames(offset)
                except ValueError:
                    raise TOCError('bad offset for file: %s' % line)

            try:
                track.file_length = model.PCM.msf_to_frames(length)
            except ValueError:
                raise TOCError('bad length for file: %s' % line)

            # Add in any silence before the track to the total length
            track.length = track.file_length + track.pregap_silence


        elif line.startswith('SILENCE '):
            track.pregap_silence = get_toc_msf_arg(line)

        elif line.startswith('START '):
            track.pregap_offset = get_toc_msf_arg(line)

        elif line.startswith('INDEX '):
            # Adjust indices to be relative start of track instead
            # of pregap
            track.index.append(get_toc_msf_arg(line)
                               + track.pregap_offset)

        elif line.startswith('ISRC '):
            track.isrc = get_toc_string_arg(line)

        elif line.startswith('DATAFILE '):
            pass

        elif line != '':
            raise TOCError('unexpected line: %s' % line)


    if track is not None:
        disc.add_track(track)

    # Make sure we did read an audio disc
    if not disc.tracks:
        raise TOCError('no audio tracks on disc')

    return disc


#
# TOC parser helper classes
#

class CDText:
    LANGUAGE_MAP_RE = re.compile(r'LANGUAGE_MAP +\{')
    LANGUAGE_RE = re.compile(r'LANGUAGE +([0-9]+) +\{ *$')
    MAPPING_RE = re.compile(r'\b([0-9]+)\s*:\s*([0-9A-Z]+)\b')

    def __init__(self):
        self.language = None

    def parse(self, line, toc_iter, for_disc = False):
        """Parse a CD_TEXT block.

        Returns a dict with the extracted values, if any.
        """

        info = None

        if line.strip() != '{':
            raise TOCError('expected "\{" but got "{0}"'.format(line))

        for line in toc_iter:
            if line == '}':
                return info

            m = self.LANGUAGE_MAP_RE.match(line)
            if m:
                if not for_disc:
                    raise TOCError('unexpected LANGUAGE_MAP in track CD_TEXT block')

                self.parse_language_map(line[m.end():], toc_iter)
                continue

            m = self.LANGUAGE_RE.match(line)
            if m:
                if self.language is None:
                    # No LANGUAGE_MAP, so just use whatever language
                    # ID we find here (it's probably 0)
                    self.language = m.group(1)

                if self.language == m.group(1):
                    info = self.parse_language_block(toc_iter)
                else:
                    # Just parse and throw away the result
                    self.parse_language_block(toc_iter)

                continue

            raise TOCError('unexpected CD_TEXT line: {0}'.format(line))

        raise TOCError('unexpected EOF in CD_TEXT block')


    def parse_language_map(self, line, toc_iter):
        i = line.find('}')
        if i != -1:
            # entire mapping on one line
            mapstr = line[:i]
        else:
            mapstr = line
            for line in toc_iter:
                i = line.find('}')
                if i != -1:
                    # end of mapping
                    mapstr += ' ' + line[:i]
                    break
                else:
                    mapstr += ' ' + line

        mappings = self.MAPPING_RE.findall(mapstr)
        for langnum, langcode in mappings:
            # Find an English code
            if langcode == '9' or langcode == 'EN':
                self.language = langnum
                return

        # Use first language mapping, if any
        if mappings:
            self.language = mappings[0][0]
        else:
            raise TOCError('found no language mappings: {0}'.format(mapstr))


    def parse_language_block(self, toc_iter):
        info = {}
        for line in toc_iter:
            if line == '}':
                return info
            elif line.startswith('TITLE '):
                info['title'] = get_toc_string_arg(line) or None
            elif line.startswith('PERFORMER '):
                info['artist'] = get_toc_string_arg(line) or None
            elif '{' in line:
                if '}' not in line:
                    self.skip_binary_data(toc_iter)

        raise TOCError('unexpected EOF in CD_TEXT LANGUAGE block')

    def skip_binary_data(self, toc_iter):
        for line in toc_iter:
            if '}' in line:
                return

        raise TOCError('unexpected EOF in binary CD_TEXT data')


def iter_toc_lines(toc):
    for line in toc.split('\n'):
        # Strip comments and whitespace
        p = line.find('//')
        if p != -1:
            line = line[:p]

        line = line.strip()

        # Hand over non-empty lines
        if line:
            yield line


def get_toc_string_arg(line):
    """Parse out a string argument from a TOC line."""
    s = line.find('"')
    if s == -1:
        raise TOCError('no string argument in line: %s' % line)

    e = line.find('"', s + 1)
    if s == -1:
        raise TOCError('no string argument in line: %s' % line)

    return line[s + 1 : e]


def get_toc_msf_arg(line):
    """Parse an MSF from a TOC line."""

    p = line.split()
    if len(p) != 2:
        raise TOCError(
            'expected a single MSF argument in line: %s' % line)

    try:
        return model.PCM.msf_to_frames(p[1])
    except ValueError:
        raise TOCError('bad MSF in line: %s' % line)
