# codplayer - test (parts of) the player module
#
# Copyright 2013 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import unittest

from .. import player

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
        
