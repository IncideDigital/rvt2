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
from base.commands import run_command

from base.utils import check_folder
from plugins.common.RVT_files import GetFiles
import base.job


class ActivitiesCache(base.job.BaseModule):

    def run(self, path=""):
        """ Parses activities cache

        """

        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.logger().info("Parsing Activities Cache files")
        vss = self.myflag('vss')

        if vss:
            base_path = self.myconfig('voutdir')
        else:
            base_path = self.myconfig('outdir')
        check_folder(base_path)

        activities = self.search.search("/ConnectedDevicesPlatform/.*/ActivitiesCache.db$")

        activities_cache_parser = self.myconfig('activities_cache_parser', os.path.join(self.myconfig('rvthome'), '.venv/bin/winactivities2json.py'))
        python3 = self.myconfig('python3', os.path.join(self.myconfig('rvthome'), '.venv/bin/python3'))

        for act in activities:
            with open(os.path.join(base_path, '{}_activitycache_{}.json'.format(act.split('/')[2], act.split('/')[-2])), 'w') as out_file:
                run_command([python3, activities_cache_parser, '-s', act], from_dir=self.myconfig('casedir'), stdout=out_file)
        return []
