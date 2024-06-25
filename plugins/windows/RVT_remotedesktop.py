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


import datetime
import re
import os

import base.job
from base.utils import check_folder, save_csv

class Teamviewer_connections(base.job.BaseModule):
    """ Extracts teamviewer connections information """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the Connections_incoming.txt or Connections.txt file
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        partition = ''
        user = ''

        srch = re.search(r'/(p\d{1,2})/', path)
        if srch:
            partition = srch.group(1)
        srch = re.search(r'/p\d{1,2}/Users/([^/]*)/', path)
        if srch:
            user = srch.group(1)

        lfields = False

        if path.endswith('incoming.txt'):
            srch = re.compile(r'^(\d+)\s+([^\t]+)\s+(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})\s+(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})\s+(\S+)\s+(\w+)')
            lfields = True
        else:
            srch = re.compile(r'^(\d+)\s+(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})\s+(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})\s+(\S+)\s+(\w+)')

        with open(path, 'r') as fin:
            for line in fin:
                if len(line) < 2:
                    continue
                fields = srch.search(line)
                if not fields:
                    self.logger().warning(f'Unable to parse line: {line}')
                    continue
                if lfields:
                    yield {
                           'startdate': str(datetime.datetime.strptime(fields.group(3), "%d-%m-%Y %H:%M:%S")),
                           'enddate': str(datetime.datetime.strptime(fields.group(4), "%d-%m-%Y %H:%M:%S")),
                           'teamviewer.hostname': fields.group(2).strip(),
                           'id_connection': fields.group(1),
                           'machine.hostname': fields.group(5),
                           'mode': fields.group(6),
                           'partition': partition}
                else:
                    yield {
                           'startdate': str(datetime.datetime.strptime(fields.group(2), "%d-%m-%Y %H:%M:%S")),
                           'enddate': str(datetime.datetime.strptime(fields.group(3), "%d-%m-%Y %H:%M:%S")),
                           'machine.hostname': fields.group(4),
                           'id.connection': fields.group(1),
                           'mode': fields.group(5),
                           'partition': partition,
                           'winuser': user}


class Anydesk(base.job.BaseModule):
    """ Extracts information about anydesk logs """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the ad.trace file
        """

        self.check_params(path, check_path=True, check_path_exists=True)
        base_path = self.myconfig('outdir')
        check_folder(base_path)

         # Induce "partition" and "user" from "path". If path is in ProgramData, no user is assigned
        partition = ''
        user = ''
        srch = re.search(r'/(p\d{1,2})/', path)
        if srch:
            partition = srch.group(1)
        srch = re.search(r'/p\d{1,2}/Users/([^/]*)/', path)
        if srch:
            user = srch.group(1)
        outfile = os.path.join(base_path, 'anydesk_{}{}.csv'.format(partition, f'_{user}' if user else ''))
        save_csv(self._process_anydesk_log(path), outfile=outfile, file_exists='OVERWRITE', quoting=0)

    def _process_anydesk_log(self, path):
        # Get only significant events and skip the rest
        regex = re.compile(r'(External address|anynet.connection_mgr|Incoming session|Sending a connection request|Client-ID|app.prepare_task|Files|Logged|Connecting to|Accept request from|New user data)')

        result = {}
        with open(path, 'r') as fin:
            for line in fin:
                if regex.search(line):
                    result['log.level'] = line[:8].strip()
                    result['@timestamp'] = line[8:31]
                    result['log.syslog.appname'] = line[31:42].strip()
                    #result['id1'] = line[43:49].strip()
                    #result['id2'] = line[50:56].strip()
                    result['log.logger'] = line[56:94].strip()
                    result['message'] = line[97:].strip()
                    yield result

