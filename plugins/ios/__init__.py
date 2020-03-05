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

""" An RVT2 plugin to parse iOS backups.

In order to use these plugins, you'll need a Tika server and/or an ElasticSearch server running  in the network.

Jobs
~~~~

:ios: Run all jobs.

:plugins.ios.Unback: mount an iOS backup. The backup can be a zip file or a directory.

"""

import os
import base.job


class IOSModule(base.job.BaseModule):
    """ A base class for the modules for iOS. """
    def database(self, path):
        self.logger().debug('Searching for an iOS database in %s', path)
        database_file = None
        for filename in ['Manifest.mbdb-decrypted', 'Manifest.db-decrypted', 'Manifest.mbdb', 'Manifest.db']:
            if os.path.isfile(os.path.join(path, filename)):
                database_file = filename
                break
        if database_file is None:
            if self.myflag('stop_on_error'):
                raise base.job.RVTError('An iOS database was not found. Is the path a (decrypted) iOS backup?')
            else:
                self.logger().warning('An iOS database was not found. Is the path a (decrypted) iOS backup?')
        return database_file
