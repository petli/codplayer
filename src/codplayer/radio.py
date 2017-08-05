# codplayer - radio station configuration class
#
# Copyright 2013-2017 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

class Station(object):
    """Radio station configuration:

    id: station id, used to select which station to play
    url: mp3 stream URL
    name: human-readable station name
    """

    def __init__(self, id, url, name):
        self.id = id
        self.url = url
        self.name = name
