#!/usr/bin/env python3
#
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


import os
import sqlite3
import biplist
import plugins.ios
import base.utils
import collections


def _mode_number2string(isdir, mode):
    """
    Convert permissions expressed as number to a string, as the body
    format of TSK3 needs. Check: https://wiki.sleuthkit.org/index.php?title=Body_file

    Parameters:
        isdir (bool): If True, the mode is of a directory
        mode (int): the permission mode, expressed as an integer

    >>> _mode_number2string(True, 0o755)
    'd/drwxr-xr-x'

    >>> _mode_number2string(False, 0o644)
    'r/rrw-r--r--'

    >>> _mode_number2string(False, 644)
    'r/r-w----r--'

    >>> _mode_number2string(False, 0o1644)
    'r/rrw-r--r--'

    >>> _mode_number2string(False, 0o44)
    'r/r---r--r--'
    """
    strmodes = ['---', '--x', '-w-', '-wx', 'r--', 'r-x', 'rw-', 'rwx']
    user_mode = strmodes[int((mode & 0o700) / 64)]
    group_mode = strmodes[int((mode & 0o070) / 8)]
    others_mode = strmodes[(mode & 0o007)]
    dirmark = 'd/d' if isdir else 'r/r'
    return '{}{}{}{}'.format(dirmark, user_mode, group_mode, others_mode)


class Timeline(plugins.ios.IOSModule):
    """
    Module that parses the file Manifest.db and generates a timeline.

    The run method yields an OrderedDict with the fields in TSK3 body file.

    Warning:
        We couldn't identify a last modification time field in the backup. Last modification time is used instead.
    """

    def run(self, path):
        """
        Parameters:
            path (str): The path to the directory where the backup was unbacked.

        Yields:
            An *OrderedDict* with the fields in TSK3 BODY file.
        """
        self.logger().debug('Parsing: %s', path)
        self.check_params(path, check_path=True, check_path_exists=True)

        database = self.database(path)

        if database is None:
            return []

        with sqlite3.connect('file://{}/{}?mode=ro'.format(path, database), uri=True) as conn:
            c = conn.cursor()
            for row in c.execute('SELECT * FROM Files'):
                name = os.path.join(row[1], row[2])
                relative_path = base.utils.relative_path(os.path.join(path, name), self.myconfig('casedir'))
                plist = biplist.readPlistFromString(row[4])
                yield collections.OrderedDict(
                    file_md5=0,
                    path=relative_path,
                    file_inode=plist['$objects'][1]['InodeNumber'],
                    file_mode=_mode_number2string(row[3] == 2, plist['$objects'][1]['InodeNumber']),
                    file_uid=plist['$objects'][1]['UserID'],
                    file_gid=plist['$objects'][1]['GroupID'],
                    file_size=plist['$objects'][1]['Size'],
                    file_access=plist['$objects'][1]['LastModified'],   # I couldn't find an access timestamp. Copy last modified
                    file_modified=plist['$objects'][1]['LastModified'],
                    file_changerecord=plist['$objects'][1]['LastStatusChange'],
                    file_birth=plist['$objects'][1]['Birth']
                )
