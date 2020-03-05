# Copyright (C) INCIDE Digital Data S.L.
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# animation code extracted from https://gist.github.com/Y4suyuki/6805818

import base.job
import time
import sys


class Case_Solve(base.job.BaseModule):
    """ Mount all partitions in a disk and then run from_module. """

    def run(self, path=None):
        txt = """MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMMMMMMM+          ,MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMMMMI                MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMM+                   ~MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMM            MMM         MMMMMMMMMMMMMM   MMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMM8             MMM          MMMMMMMMMMMMM   MMMMMMMM   IMMMMMMMMMMMMMMM
MMMMMMMMM+                          +MMMMMMMMMMMMMMMMMMMMMMMM   IMMMMMMMMMMMMMMM
MMMMMMMMM?              MMM   MMVMMMMMM:       +MM   MMM77777   IMM8      ,MMMMM
MMMMMMMMDi              MMM   MMM=  MMM~   MM   +M   MN         IMI   MM   :MMMM
MMMMMMMM~               MMM   MM+   MMM   MMMMMMMM   M?   MMM   IMI         MMMM
MMMMMMMM~               MMM   MM+   MMM   MMMMMMMM   M+   MMM   IMI   MMMMMMMMMM
MMMMMMMMD               MMM   MM+   MMM~   MM   :M   MD         IMI   MM   ~MMMM
MMMMMMMMM?              MMM   MM?   MMMM.      ~MM   MMM+       ?MM8      ,MMMMM
MMMMMMMMM+                          IMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMM8                         MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMM                       MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMM                    ?MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMMMM                ,MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMMMMMM:          ~MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM
MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM

********************************************************************************
* An expert team from INCIDE is comming to your place. Please wait ...         *
********************************************************************************
"""

        self.print(txt)

        animation = "|/-\\"

        for i in range(100):
            time.sleep(0.1)
            sys.stdout.write("\r" + animation[i % len(animation)])
            sys.stdout.flush()
        print()
        txt = """evidence found!
Police has been notified.
Suspect is under arrest.
Writing down expert witness report....
Trial begins ....
Trial ends ....
Guilty as charged!!!
"""
        self.print(txt)

    def print(self, txt):
        for i in txt:
            time.sleep(0.005)
            sys.stdout.write(i)
            sys.stdout.flush()
