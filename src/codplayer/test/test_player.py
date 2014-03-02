# codplayer - test (parts of) the player module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
import threading
import time
import sys
import traceback
import os

from .. import player
from .. import source
from .. import sink
from .. import model
from .. import audio

debug = os.getenv('DEBUG_TEST', 'fake-string-to-disable-logging')

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
        


#
# Transport test and helper classes
#

class TransportForTest(player.Transport):
    """Some synchronisation to let the test cases detect when the
    Transport has updated the state.
    """
    
    def __init__(self, test, *args):
        self._test_id = test.id()
        self._test_state_written = threading.Event()
        super(TransportForTest, self).__init__(DummyPlayer(test), *args)
        
    def write_state(self, *args):
        if debug in self._test_id:
            sys.stderr.write('{0._test_id}: {0.state}\n'.format(self))
        self._test_state_written.set()

    def write_disc(self, *args):
        pass
        

class DummySource(source.Source):
    """Packet source generating dummy packets, each a second long.
    """
    TRACK_LENGTH_SECS = 1000
    TRACK_LENGTH_FRAMES = TRACK_LENGTH_SECS * model.PCM.rate
    
    def __init__(self, disc_id, num_tracks, num_packets = None):
        disc = model.DbDisc()
        disc.disc_id = disc_id
        disc.audio_format = model.PCM
        
        for i in range(num_tracks):
            track = model.DbTrack()
            track.number = i + 1
            track.length = self.TRACK_LENGTH_FRAMES
            disc.tracks.append(track)

        super(DummySource, self).__init__(disc)

        # Inifinite isn't really that, so we know the test eventually stops
        self.num_packets = num_packets or self.TRACK_LENGTH_SECS

        
    def iter_packets(self, track_number, packet_rate):
        track = self.disc.tracks[track_number]

        for i in xrange(self.num_packets):
            packet = audio.AudioPacket(self.disc, track, track_number,
                                       i * model.PCM.rate, 1)
            packet.data = '0123456789abcdef'
            yield packet
            

class DummySink(sink.Sink):
    def __init__(self, test, *expect):
        self.test = test
        self.id = test.id()
        self.expect = list(expect)
        self.expect.reverse()
        
    def on_call(self, func, *args):
        if debug in self.id:
            sys.stderr.write('{0}: {1}{2}\n'.format(self.id, func, args))

        if not self.expect:
            self.test.fail('unexpected additional call {0}{1}'.format(func, args))

        e = self.expect.pop()
        self.test.assertEqual(e.func, func, e.msg)

        if e.checks:
            try:
                e.checks(*args)
            except:
                self.test.fail(traceback.format_exc())

        if e.ret:
            try:
                return e.ret(*args)
            except:
                self.test.fail(traceback.format_exc())
            
        
    def done(self):
        if self.expect:
            self.test.fail('test finished unexpectedly, {0} events remaining'.format(len(self.expect)))
        
    def pause(self):
        return self.on_call('pause')

    def resume(self):
        self.on_call('resume')

    def stop(self):
        self.on_call('stop')

    def start(self, format):
        self.on_call('start', format)

    def add_packet(self, packet, offset):
        return self.on_call('add_packet', packet, offset)

    def drain(self):
        return self.on_call('drain')


class Expect(object):
    def __init__(self, func, msg = None, checks = None, ret = None):
        self.func = func
        self.msg = msg
        self.checks = checks
        self.ret = ret
        

class DummyPlayer:
    def __init__(self, test):
        self.id = test.id()
        
    def log(self, msg, *args, **kwargs):
        if debug in self.id:
            sys.stderr.write('{0}: {1}: {2}\n'.format(
                    self.id, threading.current_thread().name,
                    msg.format(*args, **kwargs)))
        
    debug = log
    cfg = None

# Actual test cases follow
    
class TestTransport(unittest.TestCase):
    longMessage = True
    
    def test_working_play_stop_at_end(self):
        # Single track with three packets
        src = DummySource('disc1', 1, 3)

        # Delay one packet at a time in a dummy buffer
        buf = []

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.track, 1, 'should start playing first track'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.track_number, 0, 'should be first track record'),
                    self.assertEqual(packet.track.number, 1, 'should be first track number'),
                    self.assertEqual(packet.abs_pos, 0, 'should be first packet'),
                    self.assertEqual(offset, 0),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should set by Transport before getting update from sink'),
                    self.assertEqual(t.state.disc_id, 'disc1'),
                    self.assertEqual(t.state.no_tracks, 1),
                    self.assertEqual(t.state.length, src.TRACK_LENGTH_SECS),
                    self.assertEqual(t.state.track, 1),
                    self.assertEqual(t.state.position, 0),

                    # buffer the packet
                    buf.append(packet),
                    ),

                   ret = lambda packet, offset: (len(packet.data), None, None),
                   ),

            Expect('add_packet', 'should add second packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 1 * model.PCM.rate, 'should be second packet'),
                    self.assertEqual(offset, 0),

                    self.assertIs(t.state.state, player.State.PLAY),
                    self.assertEqual(t.state.position, 0,
                                     'state should not have been updated yet'),

                    # buffer the packet
                    buf.append(packet),
                    ),

                   # Return first packet as being played
                   ret = lambda packet, offset: (len(packet.data), buf.pop(0), None),
                   ),

            Expect('add_packet', 'should add third packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 2 * model.PCM.rate, 'should be third packet'),
                    self.assertEqual(offset, 0),

                    self.assertIs(t.state.state, player.State.PLAY),
                    self.assertEqual(t.state.position, 0,
                                     'state should show first packet'),

                    # buffer the packet
                    buf.append(packet),
                    ),

                   # Return second packet as being played
                   ret = lambda packet, offset: (len(packet.data), buf.pop(0), None),
                   ),

            Expect('drain', 'should be draining buffered packet',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY),
                    self.assertEqual(t.state.position, 1,
                                     'state should show second packet'),
                    ),

                   # Return third packet as being played, but keep in buffer
                   ret = lambda: (buf[0], None),
                   ),

            Expect('drain', 'should be draining still buffered packet',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY),
                    self.assertEqual(t.state.position, 2,
                                     'state should show third packet'),
                    ),

                   # Return third packet as being played and empty buffer
                   ret = lambda: (buf.pop(0), None),
                   ),

            Expect('drain', 'final call to be notified that draining is done',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY),
                    self.assertEqual(t.state.position, 2,
                                     'state should show third packet'),

                    # Allow test to detect that state has updated
                    t._test_state_written.clear(),
                    ),

                   # Tell transport that buffer is empty
                   ret = lambda: None,
                   ),

            Expect('stop', 'should call stop at end of disc',
                   checks = lambda: (

                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                ),
            )
        
        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')
        self.assertTrue(t._test_state_written.wait(5), 'timeout waiting for state to update')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP,
                         'transport should stop at end of disc')
        self.assertEqual(t.state.length, 0)
        self.assertEqual(t.state.track, 0)
        self.assertEqual(t.state.position, 0)


    def test_writing_partial_packet(self):
        # Single track with single packet
        src = DummySource('disc1', 1, 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(offset, 0),
                    ),

                   ret = lambda packet, offset: (4, packet, None),
                   ),

            Expect('add_packet', 'should remaining bytes in first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(offset, 4),
                    ),

                   ret = lambda packet, offset: (len(packet.data) - 4, packet, None),
                   ),

            Expect('drain', 'final call to be notified that draining is done',
                   checks = lambda: (
                    # Allow test to detect that state has updated
                    t._test_state_written.clear(),
                    ),

                   # Tell transport that buffer is empty
                   ret = lambda: None,
                   ),

            Expect('stop', 'should call stop at end of disc',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')
        self.assertTrue(t._test_state_written.wait(5), 'timeout waiting for state to update')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP,
                         'transport should stop at end of disc')


    def test_stopping(self):
        # Single track with lots of packets
        src = DummySource('disc1', 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we stop()'),

                    # Tell the transport to stop
                    t.stop(),

                    self.assertIs(t.state.state, player.State.STOP,
                                  'state should be STOP immediately, since this is a disruptive change'),
                    self.assertEqual(t.state.length, 0),
                    self.assertEqual(t.state.track, 0),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                   ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP)


    def test_eject(self):
        # Single track with lots of packets
        src = DummySource('disc1', 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we stop()'),

                    # Tell the transport to eject the disc
                    t.eject(),

                    self.assertIs(t.state.state, player.State.NO_DISC,
                                  'state should be NO_DISC immediately, since this is a disruptive change'),
                    self.assertEqual(t.state.disc_id, None),
                    self.assertEqual(t.state.no_tracks, 0),
                    self.assertEqual(t.state.length, 0),
                    self.assertEqual(t.state.track, 0),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                   ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.NO_DISC)


    def test_stop_at_end_and_play_again(self):
        # Single track with single packet
        src = DummySource('disc1', 1, 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add only packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(offset, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('drain', 'final call to be notified that draining is done',
                   checks = lambda: (
                    # Allow test to detect that state has updated
                    t._test_state_written.clear(),
                    ),

                   # Tell transport that buffer is empty
                   ret = lambda: None,
                   ),

            Expect('stop', 'should call stop at end of disc',
                   checks = lambda: (
                    # Allow test case to sync the middle of the test
                    done.set(),
                    ),
                ),

            Expect('start', 'should call start on play',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.track, 1, 'should start playing first track'),
                    ),
                ),

            Expect('add_packet', 'should add only packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(offset, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('drain', 'final call to be notified that draining is done',
                   checks = lambda: (
                    # Allow test to detect that state has updated
                    t._test_state_written.clear(),
                    ),

                   # Tell transport that buffer is empty
                   ret = lambda: None,
                   ),

            Expect('stop', 'should call stop at end of disc',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for first run to finish')
        self.assertTrue(t._test_state_written.wait(5), 'timeout waiting for first run state to update')

        self.assertEqual(t.state.state, player.State.STOP,
                         'transport should stop at end of disc')
        
        # Now play it again
        done.clear()
        t.play()

        # Wait for second run to finish
        self.assertTrue(done.wait(5), 'timeout waiting for second run to finish')
        self.assertTrue(t._test_state_written.wait(5), 'timeout waiting for second run state to update')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP,
                         'transport should stop at end of disc')


    def test_stopping_and_play_again(self):
        # Single track with lots of packets
        src = DummySource('disc1', 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.track_number, 0, 'should be first track record'),
                    self.assertEqual(packet.track.number, 1, 'should be first track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we stop()'),

                    # Tell the transport to stop
                    t.stop(),

                    self.assertIs(t.state.state, player.State.STOP,
                                  'state should be STOP immediately, since this is a disruptive change'),
                    self.assertEqual(t.state.length, 0),
                    self.assertEqual(t.state.track, 0),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                   ),

            Expect('start', 'should call start on playing disc again',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.track, 1, 'should start playing first track'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.track_number, 0, 'should be first track record'),
                    self.assertEqual(packet.track.number, 1, 'should be first track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we stop()'),

                    # Tell the transport to stop
                    t.stop(),

                    self.assertIs(t.state.state, player.State.STOP,
                                  'state should be STOP immediately, since this is a disruptive change'),
                    self.assertEqual(t.state.length, 0),
                    self.assertEqual(t.state.track, 0),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                   ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for first run to finish')

        # Now play it again
        done.clear()
        t.play()

        # Wait for second run to finish
        self.assertTrue(done.wait(5), 'timeout waiting for second run to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP,
                         'transport should stop at end of disc')


    def test_new_source_while_playing(self):
        # Single track with lots of packets
        src1 = DummySource('disc1', 1)

        # Single track with one packet
        src2 = DummySource('disc2', 1, 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on first disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.disc_id, 'disc1')
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we change the disc'),

                    # Tell the transport to switch to the next source
                    t.new_source(src2),

                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING immediately, since this is a disruptive change'),
                    self.assertEqual(t.state.disc_id, 'disc2'),
                    self.assertEqual(t.state.no_tracks, 1),
                    self.assertEqual(t.state.track, 1, 'should start playing first track'),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport on changing disc'),

            Expect('start', 'should call start on second disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.track, 1, 'should start playing first track'),
                    self.assertEqual(t.state.disc_id, 'disc2')
                    ),
                ),

            Expect('add_packet', 'should add only packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(offset, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('drain', 'final call to be notified that draining is done',
                   checks = lambda: (
                    # Allow test to detect that state has updated
                    t._test_state_written.clear(),
                    ),

                   # Tell transport that buffer is empty
                   ret = lambda: None,
                   ),

            Expect('stop', 'should call stop at end of disc',
                   checks = lambda: (
                    # Allow test case to sync the middle of the test
                    done.set(),
                    ),
                ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src1)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP)
        self.assertEqual(t.state.disc_id, 'disc2')


    def test_next_track(self):
        # Two tracks with two packets each
        src = DummySource('disc1', 2, 2)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.track, 1, 'should start playing first track'),
                    ),
                ),

            Expect('add_packet', 'should add first packet of first track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.track_number, 0, 'should be first track record'),
                    self.assertEqual(packet.track.number, 1, 'should be first track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we next()'),

                    # Tell the transport to move to the next track
                    t.next(),

                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING while waiting for next track to start'),
                    self.assertEqual(t.state.track, 2, 'track should be updated'),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport on switching track',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should still be PLAY, since this is called within next()'),
                    self.assertEqual(t.state.track, 1, 'track should still be the first track'),
                    self.assertEqual(t.state.position, 0),
                    ),
                   ),

            Expect('start', 'should call start for new track',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should still be WORKING while waiting for next track to start'),
                    self.assertEqual(t.state.track, 2, 'track should still be the pending track'),
                    self.assertEqual(t.state.position, 0),
                    ),
                ),

            Expect('add_packet', 'should add first packet of second track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.track_number, 1, 'should be second track record'),
                    self.assertEqual(packet.track.number, 2, 'should be second track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we next()'),

                    # Tell the transport to move to the next track (which will stop)
                    t.next(),

                    self.assertIs(t.state.state, player.State.STOP,
                                  'state should be STOP since there are no more tracks'),
                    self.assertEqual(t.state.track, 0, 'track should be updated'),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should call stop at end of disc',
                   checks = lambda: (
                    # Allow test case to sync the middle of the test
                    done.set(),
                    ),
                ),
           )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP)


    def test_prev_track(self):
        # Two tracks with four packets each, to be able to test restarting track
        src = DummySource('disc1', 2, 4)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    self.assertEqual(t.state.track, 2, 'should start playing second track'),
                    ),
                ),

            Expect('add_packet', 'should add first packet of second track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 0, 'should be first packet'),
                    self.assertEqual(packet.track_number, 1, 'should be second track record'),
                    self.assertEqual(packet.track.number, 2, 'should be second track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when starting to play track'),
                    self.assertEqual(t.state.position, 0, 'should start playing from start of track'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('add_packet', 'should add second packet of second track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 1 * model.PCM.rate, 'should be second packet'),
                    self.assertEqual(t.state.position, 0, 'position should still be first packet'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('add_packet', 'should add third packet of second track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 2 * model.PCM.rate, 'should be third packet'),
                    self.assertEqual(t.state.position, 1, 'position should be second packet'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('add_packet', 'should add fourth packet of second track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 3 * model.PCM.rate, 'should be fourth packet'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we prev()'),
                    self.assertEqual(t.state.position, 2, 'position should be third packet when we prev()'),

                    # Tell transport to restart from start of the second track
                    t.prev(),

                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING while waiting for track to restart'),
                    self.assertEqual(t.state.track, 2, 'should still be the second track'),
                    self.assertEqual(t.state.position, 0, 'position should be start of track'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport on switching track',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should still be PLAY, since this is called within prev()'),
                    self.assertEqual(t.state.track, 2, 'track should still be the second track'),
                    self.assertEqual(t.state.position, 2, 'position should still be third packet'),
                    ),
                   ),

            Expect('start', 'should call start on restart of track',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should still be WORKING while waiting for track to restart'),
                    self.assertEqual(t.state.track, 2, 'track should still be the second track'),
                    self.assertEqual(t.state.position, 0, 'position should still be start of track'),
                    ),
                ),

            Expect('add_packet', 'should add first packet of second track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 0, 'should be first packet'),
                    self.assertEqual(packet.track_number, 1, 'should be second track record'),
                    self.assertEqual(packet.track.number, 2, 'should be second track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we prev()'),
                    self.assertEqual(t.state.track, 2, 'track should be the second track when we prev()'),

                    # Tell the transport to move to the previous track
                    t.prev(),

                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING while waiting for prev track to start'),
                    self.assertEqual(t.state.track, 1, 'should be the first track'),
                    self.assertEqual(t.state.position, 0, 'position should be start of track'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport on switching track',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should still be PLAY, since this is called within prev()'),
                    self.assertEqual(t.state.track, 2, 'track should still be the second track'),
                    self.assertEqual(t.state.position, 0, 'position should still be first packet'),
                    ),
                   ),

            Expect('start', 'should call start on restart of track',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should still be WORKING while waiting for track to restart'),
                    self.assertEqual(t.state.track, 1, 'track should still be the first track'),
                    self.assertEqual(t.state.position, 0, 'position should still be start of track'),
                    ),
                ),

            Expect('add_packet', 'should add first packet of first track',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 0, 'should be first packet'),
                    self.assertEqual(packet.track_number, 0, 'should be first track record'),
                    self.assertEqual(packet.track.number, 1, 'should be first track number'),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we prev()'),
                    self.assertEqual(t.state.track, 1, 'track should be the first track when we prev()'),

                    # Tell the transport to move to the previous track, which will stop on start of disc
                    t.prev(),

                    self.assertIs(t.state.state, player.State.STOP,
                                  'state should be STOP since we prev() at start of disc'),
                    self.assertEqual(t.state.track, 0, 'track should be updated'),
                    self.assertEqual(t.state.position, 0),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should call stop when prev() at start of disc',
                   checks = lambda: (
                    # Allow test case to sync the middle of the test
                    done.set(),
                    ),
                ),
           )

        # Kick off test on second track and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src, 1)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP)


    def test_pause_and_resume(self):
        # Single track with lots of packets
        src = DummySource('disc1', 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 0, 'should be first packet'),
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we pause()'),

                    # Tell the transport to pause
                    t.pause(),

                    self.assertIs(t.state.state, player.State.PAUSE,
                                  'state should be PAUSE immediately, since the sink "paused" itself'),
                    self.assertEqual(t.state.position, 0, 'should be paused on first packet'),
                    ),

                   # Accept packet despite pause - let's pretend it's buffered
                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('pause', 'should be told to pause by transport',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should still be PLAY, since this is called within pause()'),
                    ),

                   # Tell transport that we are "paused"
                   ret = lambda: True
                   ),

            Expect('add_packet', 'should add second packet while paused',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 1 * model.PCM.rate, 'should be second packet'),
                    self.assertIs(t.state.state, player.State.PAUSE),

                    # Tell transport to resume again
                    t.play(),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY immediately'),
                    self.assertEqual(t.state.position, 0, 'position should still be first packet'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('resume', 'should be told to resume by transport',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PAUSE,
                                  'state should still be PAUSE, since this is called within play()'),
                    ),
                   ),

            Expect('add_packet', 'should add third packet after resume',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 2 * model.PCM.rate, 'should be third packet'),
                    self.assertIs(t.state.state, player.State.PLAY),

                    # Tell transport to stop the test
                    t.stop(),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                   ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP)


    def test_play_pause_command(self):
        # Single track with lots of packets
        src = DummySource('disc1', 1)

        # Wait for test to finish on an event
        done = threading.Event()

        expects = DummySink(
            self,
            Expect('start', 'should call start on new disc',
                   checks = lambda format: (
                    self.assertIs(format, model.PCM),
                    self.assertIs(t.state.state, player.State.WORKING,
                                  'state should be WORKING before any packets have been read'),
                    ),
                ),

            Expect('add_packet', 'should add first packet',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 0, 'should be first packet'),
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY when we play_pause()'),

                    # Tell the transport to toggle into pause
                    t.play_pause(),

                    self.assertIs(t.state.state, player.State.PAUSE,
                                  'state should be PAUSE immediately, since the sink "paused" itself'),
                    self.assertEqual(t.state.position, 0, 'should be paused on first packet'),
                    ),

                   # Accept packet despite pause - let's pretend it's buffered
                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('pause', 'should be told to pause by transport',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should still be PLAY, since this is called within play_pause()'),
                    ),

                   # Tell transport that we are "paused"
                   ret = lambda: True
                   ),

            Expect('add_packet', 'should add second packet while paused',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 1 * model.PCM.rate, 'should be second packet'),
                    self.assertIs(t.state.state, player.State.PAUSE),

                    # Tell transport to resume again
                    t.play_pause(),

                    self.assertIs(t.state.state, player.State.PLAY,
                                  'state should be PLAY immediately'),
                    self.assertEqual(t.state.position, 0, 'position should still be first packet'),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('resume', 'should be told to resume by transport',
                   checks = lambda: (
                    self.assertIs(t.state.state, player.State.PAUSE,
                                  'state should still be PAUSE, since this is called within play_pause()'),
                    ),
                   ),

            Expect('add_packet', 'should add third packet after resume',
                   checks = lambda packet, offset: (
                    self.assertEqual(packet.abs_pos, 2 * model.PCM.rate, 'should be third packet'),
                    self.assertIs(t.state.state, player.State.PLAY),

                    # Tell transport to stop the test
                    t.stop(),
                    ),

                   ret = lambda packet, offset: (len(packet.data), packet, None),
                   ),

            Expect('stop', 'should be told to stop by transport',
                   checks = lambda: (
                    # Allow test case to sync the end of the test
                    done.set(),
                    ),
                   ),
            )

        # Kick off test and wait for it
        t = TransportForTest(self, expects)
        t.new_source(src)
        self.assertTrue(done.wait(5), 'timeout waiting for test to finish')

        # Check final state
        expects.done()
        self.assertEqual(t.state.state, player.State.STOP)

