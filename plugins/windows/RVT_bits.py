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
import bits
from collections import OrderedDict

import base.job
from base.utils import check_directory, save_csv, relative_path


class Bits(base.job.BaseModule):
    """ Parse Background Intelligent Transfer Service. """

    def run(self, path=""):
        base_path = self.myconfig('outdir')
        check_directory(base_path, create=True)
        self.check_params(path, check_path=False, check_path_exists=False)
        self.logger().debug("Parsing Bits database: {}".format(path))
        volume_id = relative_path(path, self.myconfig('casedir')).split("/")[2]
        outfile = os.path.join(base_path, "bitsdb_{}.csv".format(volume_id))
        self.parse_BITS(path, outfile)
        return []

    def parse_BITS(self, path, outfile):

        fields = OrderedDict([
            ('job_id', None),
            ('name', None),
            ('desc', None),
            ('type', None),
            ('priority', None),
            ('sid', None),
            ('state', None),
            ('cmd', None),
            ('args', None),
            ('file_count', 0),
            ('file_id', 0),
            ('dest_fn', None),
            ('src_fn', None),
            ('tmp_fn', None),
            ('download_size', -1),
            ('transfer_size', -1),
            ('drive', None),
            ('vol_guid', None),
            ('ctime', None),
            ('mtime', None),
            ('other_time0', None),
            ('other_time1', None),
            ('other_time2', None),
            ('carved', False)
        ])

        analyzer = bits.Bits.load_file(path)
        jobs = analyzer.parse()
        res_generator = (OrderedDict([(field, j.get(field, fields[field])) for field in fields]) for j in jobs)
        save_csv(res_generator, outfile=outfile, file_exists='OVERWRITE')
