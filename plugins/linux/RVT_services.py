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
import base.job
from base.utils import check_folder


class AnalysisServicesList(base.job.BaseModule):
    
    """ Extract the diferent Services from the list.

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('outdir', None)

    def run(self, path=None):
        mount_dir = self.myconfig('mountdir')

        for line in self.from_module.run(path):
            splitted_line = line.split(",")
            relative_path = splitted_line[0][len(mount_dir):]
            root_name = os.path.splitext(splitted_line[1])[0]
            data_to_yield = {
                'directory' : relative_path,
                'filename' : root_name
            } 
            yield data_to_yield