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
from base.utils import check_directory

from mplog_parser.main import MpLogParser
from mplog_parser.adapters.os_adapter import OsAdapter
import fnmatch


class MPlogP(MpLogParser):

    # Overrides orchestrator function to write output in UTF-8

    def orchestrator(self) -> None:
        """Runs parsers and writes results to output files."""
        for file in self._os_adapter.listdir(self._mplogs_directory):
            if fnmatch.fnmatch(file, self.mplog_file_name_pattern):
                full_path = self._os_adapter.join(self._mplogs_directory, file)
                try:
                    logs = self._os_adapter.read_file(full_path, 'r', 'UTF-16')
                except UnicodeError:
                    logs = self._os_adapter.read_file(full_path, 'r', 'UTF-8')
                self.write_results(self._rtp_perf_csv_output, self.rtp_perf_parser(logs), 'UTF-8')
                self.write_results(self._exclusion_list_output_csv, self.exclusion_list_parser(logs), 'UTF-8')
                self.write_results(self._mini_filter_unsuccessful_scan_status_output_csv,
                                   self.mini_filter_unsuccessful_scan_status_parser(logs), 'UTF-8')
                self.write_results(self._mini_filter_blocked_file_output_csv,
                                   self.mini_filter_blocked_file_parser(logs), 'UTF-8')
                self.write_results(self._lowfi_output_csv, self.lowfi_parser(logs), 'UTF-8')
                self.write_results(self._threat_command_line_csv_output, self.threatcommandline_parser(logs), 'UTF-8')
                self.write_results(self._process_image_name_csv_output, self.processimagename_parser(logs), 'UTF-8')
                self.write_results(self._detection_event_output_csv, self.detectionevent_mpsource_system_parser(logs)), 'UTF-8'
                self.write_results(self._detection_add_output_csv, self.detection_add_parser(logs), 'UTF-8')
                self.write_results(self._ems_output_csv, self.ems_parser(logs), 'UTF-8')
                self.write_results(self._original_filename_output_csv, self.originalfilename_parser(logs), 'UTF-8')
                self.write_results(self._bm_telemetry_output_csv, self.bmtelemetry_parser(logs), 'UTF-8')
                self.write_results(self._resource_scan_output_csv, self.resourcescan_parser(logs), 'UTF-8')
                self.write_results(self._threat_action_output_csv, self.threatactions_parser(logs), 'UTF-8')


class MPLog(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('volume_id', None)

    def run(self, path=""):
        """ Parses MpLog files
        """

        self.check_params(path, check_path=True, check_path_exists=True)
        outdir = self.myconfig('outdir')
        check_directory(outdir, create=True)

        defender = MPlogP(OsAdapter(), path, outdir)
        defender.orchestrator()

        return []
