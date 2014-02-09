# codplayer - audio sources
#
# Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

"""
Classes implementing sources of audio packets to be used by the player Transport.
"""

import os
import time
import errno
import threading

from . import audio

class SourceError(Exception): pass

class Source(object):
    """Abstract base class representing a source of audio packets.
    """

    def __init__(self, disc):
        self.disc = disc

    def iter_packets(self, track_number, packet_rate):
        """Iterate over audio packets from this source, starting at
        TRACK_NUMBER (counting from 0) and running at approximately
        PACKET_RATE Hz.

        Raise SourceError if running into errors, and just return
        normally at the end of the stream.

        The iterator can generate None if there isn't a packet ready
        after a delay to give control back to the transport.
        """
        raise NotImplementedError()
    

class PCMDiscSource(Source):
    """Generate audio packets from a database disc in PCM format.
    """

    def __init__(self, player, disc, is_ripping):
        super(PCMDiscSource, self).__init__(disc)

        self.player = player
        self.log = player.log
        self.debug = player.debug
        
        # Due to the Big Interpreter Lock we probably don't need any
        # thread signalling at all for these simple flags, but let's
        # play it nice.
        
        if is_ripping:
            self.is_ripping = threading.Event()
            self.is_ripping.set()
        else:
            self.is_ripping = None
            
        self.audio_file = None


    def rip_finished(self):
        """Call to inform that the any concurrent ripping process is finished."""

        if self.is_ripping:
            self.is_ripping.clear()


    def iter_packets(self, track_number, packet_rate):
        self.debug('generating packets for {0} track {1}',
                   self.disc, track_number)

        # Construct full path to data file and open it

        db_id = self.player.db.disc_to_db_id(self.disc.disc_id)
        path = os.path.join(
            self.player.db.get_disc_dir(db_id),
            self.disc.data_file_name)


        # Retry opening file if the ripping process is in progress
        # and might not have had time to create it yet

        while self.audio_file is None:
            try:
                self.debug('opening file {0}', path)
                self.audio_file = open(path, 'rb')
            except IOError, e:
                if e.errno == errno.ENOENT and self.is_ripping and self.is_ripping.is_set():
                    time.sleep(1)
                else:
                    raise SourceError('error opening file {0}: {1}'.format(path, e))

        # Iterate over all packets, reading data into them

        for p in audio.AudioPacket.iterate(self.disc, track_number, packet_rate):

            try:
                self.read_data_into_packet(p)
            except IOError, e:
                raise SourceError('error reading from file {0}: {1}'.format(path, e))

            # Send out packet to transport
            yield p

        self.debug('iterator reached end of disc, finishing')


    def read_data_into_packet(self, p):
        """Thread helper method for populating data into packet P."""

        perf_log = self.player.audio_streamer_perf_log

        length = p.length * self.disc.audio_format.bytes_per_frame

        if p.file_pos is None:
            # Silence, so send on null bytes to player
            p.data = '\0' * length

        else:
            file_pos = p.file_pos * self.disc.audio_format.bytes_per_frame

            if perf_log:
                start_read = time.time()
            
            self.audio_file.seek(file_pos)
            p.data = self.audio_file.read(length)

            if perf_log:
                now = time.time()
                perf_log.write(
                    '{0:06f} {1:06f} read {2}\n'.format(start_read, now, len(p.data)))

            length -= len(p.data)
            file_pos += len(p.data)
            
            # If we didn't get all data, iterate with a timeout until
            # it's all been read or the ripping process has stopped.
            # This is not very efficient, and there's a small race
            # condition at the end of the disc, but this should be
            # very rare so keep it unoptimised for now.

            while length > 0 and self.is_ripping and self.is_ripping.is_set():
                time.sleep(1)
                
                if perf_log:
                    start_read = time.time()

                self.audio_file.seek(file_pos)
                d = self.audio_file.read(length)

                if perf_log:
                    now = time.time()
                    perf_log.write(
                        '{0:06f} {1:06f} read {2}\n'.format(start_read, now, len(d)))

                length -= len(d)
                file_pos += len(d)

                p.data += d
                        
            # Still didn't get all data, treat it as an exception
            if length > 0:
                raise SourceError('unexpected end of file, expected at least {0} bytes'
                                  .format(length))
    
