# codplayer - test (parts of) the player module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest
from .. import command

class TestCommandReader(unittest.TestCase):
    def test_commandreader(self):
        cr = command.CommandReader()

        # Get foo
        cmds = list(cr.handle_data('foo\n'))
        self.assertListEqual(cmds, [['foo']])

        # Get nothing
        cmds = list(cr.handle_data(' cmd  2 '))
        self.assertListEqual(cmds, [])

        # Get cmd 2 as newline triggers command
        cmds = list(cr.handle_data('\n'))
        self.assertListEqual(cmds, [['cmd', '2']])

        # Get cmd 3 and 4
        cmds = list(cr.handle_data('cmd 3\ncmd 4\nc'))
        self.assertListEqual(cmds, [['cmd', '3'],
                                    ['cmd', '4']])

        # Get cmd 5
        cmds = list(cr.handle_data('md 5\n'))
        self.assertListEqual(cmds, [['cmd', '5']])



