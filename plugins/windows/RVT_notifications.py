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

import xmltodict
import re
import os

import base.job
from base.utils import check_directory, save_json


class Notifications(base.job.BaseModule):
    """ Parse Notifications database.

    based on https://inc0x0.com/2018/10/windows-10-notification-database/
    """

    def run(self, path=""):
        base_path = self.myconfig('outdir')
        check_directory(base_path, create=True)
        self.check_params(path, check_path=False, check_path_exists=False)
        srch = re.compile(r'/([^/]*)/(Documents and Settings|Users)/([^/]*)')

        srch_aux = srch.search(path)
        partition = srch_aux.group(1)
        user = srch_aux.group(3)
        self.logger().info('Extracting windows Notifications from user {} at {}'.format(user, partition))
        outfile = os.path.join(base_path, 'notifications_{}_{}.csv'.format(partition, user))
        save_json(self.parse(path), outfile=outfile, file_exists='OVERWRITE', quoting=1)

    def parse(self, path):

        query = """SELECT n.'Order', n.Id, n.Type, nh.PrimaryId AS HandlerPrimaryId, nh.CreatedTime AS HandlerCreatedTime, nh.ModifiedTime AS HandlerModifiedTime, n.Payload,
                    CASE WHEN n.ExpiryTime != 0 THEN datetime((n.ExpiryTime/10000000)-11644473600, 'unixepoch') ELSE n.ExpiryTime END AS ExpiryTime,
                    CASE WHEN n.ArrivalTime != 0 THEN datetime((n.ArrivalTime/10000000)-11644473600, 'unixepoch') ELSE n.ArrivalTime END AS ArrivalTime
                    FROM Notification n
                    INNER JOIN NotificationHandler nh ON n.HandlerID = nh.RecordID"""

        module = base.job.load_module(self.config, 'base.input.SQLiteReader', extra_config=dict(query=query))
        for line in module.run(path):
            if line['Payload']:
                try:
                    line['Payload'] = xmltodict.parse(line['Payload'])
                    yield(line)
                except Exception:
                    pass
            else:
                yield line
