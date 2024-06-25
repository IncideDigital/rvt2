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

import base.job
from plugins.linux import get_username


class CopyFilesWithUsername(base.job.BaseModule):

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        outdir = self.myconfig('outdir')
        username = get_username(path, mount_dir=self.myconfig('mountdir'),subfolder=self.myconfig('subfolder'))
        extra_config = {
            'outdir': outdir, 
            'outfile': f"{username}_{{path}}.txt"
        }
        results = list(base.job.run_job(self.config, 'base.directory.CopyFile', path=path, extra_config=extra_config))


