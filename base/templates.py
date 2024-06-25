#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2019, INCIDE Digital Data S.L.
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

""" Modules to manage mako templates. """

import base.output
import base.config
import mako.lookup
import mako.template
import mako.exceptions
import os

DEFAULT_TEMPLATE = """\
% for row in data:
- ${' '.join(map(lambda k: '{}:{}'.format(k, row[k]), row))}
% endfor\
"""


class TemplateSink(base.output.BaseSink):
    """ A _base.output.BaseSink_ that saves into a file or standard output, using a mako template.

    Configuration:
        - **template_dirs**: A space separated list of directories to load templates from. Default: current path, rvt2 path
        - **input_encoding**: The encoding of the templates. Default: *utf-8*
        - **template_file**: A file with the template. Relative to 'template_dirs'
        - **template**: The template as a string. This option is ignored if a template_file is provided.
        - **skip_on_empty_data**: If from_module doesn't return anything and this is True, do not output anything
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('template_dirs', ' '.join([os.getcwd(), self.myconfig('rvthome')]))
        self.set_default_config('input_encoding', 'utf-8')
        self.set_default_config('template_file', '')
        self.set_default_config('template', DEFAULT_TEMPLATE)
        self.set_default_config('skip_on_empty_data', 'True')

    def _template(self):
        """ Get the mako.Template from template or template_file """
        template_file = self.myconfig('template_file')
        if template_file:
            template_dirs = self.myarray('template_dirs')
            lookup = mako.lookup.TemplateLookup(directories=template_dirs, input_encoding=self.myconfig('input_encoding'))
            return lookup.get_template(template_file)
        else:
            return mako.template.Template(self.myconfig('template'))

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        data = []
        try:
            data = list(self._source(path))
            if data or not self.myflag('skip_on_empty_data'):
                with self._outputfile() as f:
                    f.write(self._template().render(data=data))
        except Exception:
            self.logger().error('Error in the template: error="%s"', mako.exceptions.text_error_template().render())
            if self.myflag('stop_on_error'):
                raise
        return iter(data)
