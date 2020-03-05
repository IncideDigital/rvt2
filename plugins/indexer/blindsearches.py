# -*- coding: utf-8 -*-
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

import os.path
import json
import base.job


class BlindSearches(base.job.BaseModule):
    """ A module to annotate documents that match a blind search.

    Configuration:
        - **keyword_tag_field**: Identification of the field to use for annotations.
          Remember ``ElasticSearchBulkSender`` allows appending to annotation lists by using a field ending in "-new"
        - **strip_match**: If true, return only the identifier of the document and the annotation, if any.
          If false, returns the whole document.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('keyword_tag_field', 'blindsearches-new')
        self.set_default_config('strip_match', 'True')

    def run(self, path=None):
        """ The path to a JSON file, output of a previous ElasticSearchAdapter. """
        self.check_params(path, check_path=True, check_path_exists=True, check_from_module=True)

        for matched_line in self.from_module.run(path):
            match = json.loads(matched_line['match'])
            if self.myflag('strip_match'):
                match = dict(_id=match['_id'])
            matched_file = matched_line.get('keyword_file', '')
            if matched_file is None:
                matched_file = ''
            match[self.myconfig('keyword_tag_field')] = '{}:{}'.format(os.path.basename(matched_file), matched_line['tag'])
            yield match
