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
from base.utils import save_csv, relative_path, check_directory


class ActivitiesCache(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('volume_id', None)

    def run(self, path=""):
        """ Parses activitiesCache.db
        """

        # Known folder GUIDs
        # "https://docs.microsoft.com/en-us/dotnet/framework/winforms/controls/known-folder-guids-for-file-dialog-custom-places"
        # Duration or totalEngagementTime += e.EndTime.Value.Ticks - e.StartTime.Ticks)
        # https://docs.microsoft.com/en-us/uwp/api/windows.applicationmodel.useractivities
        # StartTime: The start time for the UserActivity
        # EndTime: The time when the user stopped engaging with the UserActivity

        self.check_params(path, check_path=True, check_path_exists=True)
        base_path = self.myconfig('outdir')
        check_directory(base_path, create=True)

        # Load query
        query_file = self.myconfig('query_file')
        with open(query_file, 'r') as qf:
            query = qf.read()

        # Query db and create csv
        rel_path = relative_path(os.path.abspath(path), self.myconfig('casedir'))
        self.logger().debug("Parsing Activities Cache file {}".format(rel_path))
        module = base.job.load_module(self.config, 'base.input.SQLiteReader', extra_config=dict(query=query))
        if self.myconfig('volume_id'):
            outfile = os.path.join(base_path, 'activitycache_{}.csv'.format(self.myconfig('volume_id')))
        else:
            outfile = os.path.join(base_path, 'activitycache_{}_{}.csv'.format(rel_path.split('/')[-2], rel_path.split('/')[2]))
        save_csv(module.run(path), outfile=outfile, file_exists='OVERWRITE', quoting=1)

        return []


class ActivitiesCacheAnalysis(base.job.BaseModule):

    def run(self, path=""):
        """ Creates a report based on the output of ActivitiesCache.

            Arguments:
                - ** path **: Path to directory where output files from ActivitiesCache are stored
        """
        check_directory(path, error_missing=True)
        outfile = self.myconfig('outfile')
        check_directory(os.path.dirname(os.path.abspath(outfile)), create=True)

        save_csv(self.report_activities_cache(path), config=self.config, outfile=outfile, file_exists='OVERWRITE', quoting=0, encoding='utf-8')

        return []

    def report_activities_cache(self, path):
        """ Create a unique activitiescache csv for all users."""

        fields_renaming = {"StartTime": "StartTime",
                           "EndTime": "EndTime",
                           "Application": "Application",
                           "DisplayName": "DisplayName",
                           "Full Path": "FullPath",
                           "AppActivityId": "AppActivityId",
                           "App/Uri": "App/Uri",
                           "Activity_type": "ActivityType",
                           "Active Duration": "ActiveDuration",
                           "LastModified": "LastModified"}

        for file in sorted(os.listdir(path)):
            if file.startswith('activitycache'):
                # Expected file format: `activitycache_L.user_partition.csv`
                user = file[16:-8]  # delete the prefix "L."
                partition = file[-7:-4]
                for line in base.job.run_job(self.config,
                                             'base.input.CSVReader',
                                             path=os.path.join(path, file),
                                             extra_config={'delimiter': ';', 'encoding': 'utf-8'}):
                    res = {new_field: line.get(field, '') for field, new_field in fields_renaming.items()}
                    res.update({'User': user, 'Partition': partition})
                    yield res
