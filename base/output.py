#!/usr/bin/env python3
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


""" Print the results from other modules to the console or a file. """

import os
import sys
import json
import csv
import base.job
import base.config


class BaseSink(base.job.BaseModule):
    """ An abstract module that prints the results from other modules to a file or standard output.

    Do not use this module directly, but one of its extensions.

    The `from_module` of a `BaseSink` object can be a `base.job.BaseModule` or an array.
    This way, you can use sinks like this, to use common configuration.

    Example:
        Save a list into a CSV file::

            m = base.job.load_module(
                base.config.default_config, 'base.output.CSVSink',
                extra_config=dict(outfile='outfile.csv')
                from_module=[
                    dict(greeting='Hello', language='English'),
                    dict(greeting='Hola', language='Spanish')
                ]
            )
            list(m.run())


    Configuration:
        - **outfile** (str): If provided, saved to this file (absolute path) instead of standard output. CONSOLE is a special name: prints to standard output.
        - **file_exists** (str): If outfile exists, APPEND (this is the default behaviour), OVERWRITE or throw an ERROR.

    Current job section:
        - **outfile** (str): ``outfile`` can be defined in the job section if the outfile in the section is empty
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('outfile', '')
        self.set_default_config('file_exists', 'APPEND')
        self.set_default_config('encoding', 'utf-8')

    def _source(self, path):
        """ Returns the source of the data.

        - If from_module is of base.job.BaseModule, run and use it as source.
        - If not, assume from_module is a generator, list or tuple and use as source
        """
        if isinstance(self.from_module, base.job.BaseModule):
            return self.from_module.run(path)
        return self.from_module

    def _outputfile(self):
        """ Returns a file object for the output.

        The output file is:

        1. If the outfile parameter in the configuration section is CONSOLE, outputs to the standard output.
        1. If the outfile parameter in the configuration section is a filename, use this.
        1. If the outfile parameter in the configuration section is empty, follow the same logic in the job section.
        """

        outfilename = self._get_outfile()

        if not outfilename or outfilename == 'CONSOLE':
            self.logger().debug('Printing information to the standard output')
            outputfile = sys.stdout
        else:
            # print to outfilename
            self.logger().info(f'Saving output in outfile "{outfilename}"')
            file_mode = 'w'
            if os.path.exists(outfilename):
                if self.myconfig('file_exists') == 'APPEND':
                    file_mode = 'a'
                elif self.myconfig('file_exists') == 'OVERWRITE':
                    file_mode = 'w'
                else:
                    self.logger().error(f'Outfile already exist: "{outfilename}"')
                    raise TypeError('Outfile already exists: {}'.format(outfilename))

            # create the dirname, if not exists
            # if dirname is empty, outfilename is probably a relative path
            dirname = os.path.dirname(outfilename)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

            outputfile = open(outfilename, file_mode, encoding=self.myconfig('encoding'))

        return outputfile

    def _get_outfile(self):
        # read outfile from the section name (first) or the job name (second)
        outfilename = self.myconfig('outfile')
        if not outfilename:
            outfilename = self.config.get(self.config.job_name, 'outfile', None)
        return outfilename

    def run(self, path=None):
        raise base.job.RVTException('You must implement this method')


class JSONSink(BaseSink):
    """ A module that prints the results from other modules to a file or standard output as a JSON object.

    Configuration:
        - **outfile** (str): If provided, saved to this file (absolute path) instead of standard output. CONSOLE is a special name: prints to standard output.
        - **file_exists** (str): If outfile exists, APPEND (this is the default behaviour), OVERWRITE or throw an ERROR.
        - **indent** (str): Indentation value for the output. Default=None
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('indent', None)
        self.set_default_config('ensure_ascii', True)

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        outputfile = self._outputfile()
        indent = self.myconfig('indent', 0)
        if indent is not None:
            indent = int(indent)

        for fileinfo in self._source(path):
            try:
                jsondata = json.dumps(fileinfo, indent=indent, ensure_ascii=self.myflag('ensure_ascii'))
                outputfile.write(jsondata)
                outputfile.write('\n')
                yield fileinfo
            except TypeError as exc:
                if self.myflag('stop_on_error'):
                    raise
                else:
                    self.logger().warning('{}: {}'.format(exc, fileinfo.get('path', '')))

        try:
            if not outputfile == sys.stdout:
                outputfile.close()
        except Exception as exc:
            self.logger().warning(f'Exception while closing the file: {exc}')


class CSVSink(BaseSink):
    """ A module that prints the results from other modules to a file or the standard output as a CSV.

    Configuration::
        - **outfile** (str): If provided, saved to this file (absolute path) instead of standard output. CONSOLE is a special name to force printing to the standard output.
        - **file_exists** (str): If outfile exists, APPEND (this is the default behaviour), OVERWRITE or throw an ERROR.
        - **fieldnames**: If present, use these names instead of the input dictionary keys. You can use this option to order the fields.
        - **delimiter** (String): The delimiter parameter of the csv.DictWriter. "TAB" means tabulator.
        - **quotechar** (String): The quotechar of the csv.DictWriter. Defaults to \".
        - **extrasaction** (String): The extrasaction parameter of the csv.DictWriter. Defaults to "raise".
        - **restval** (String): The restval parameter of the csv.DictWriter. Defaults to the empty string.
        - **write_header** (boolean): If True (default), writes the header of the CSV file.
        - **quoting** (int): The quoting parameter of the csv.DictWriter.
        - **doublequote**: When True, the quotechar character is doubled if found. When False, the escapechar is used as a prefix to the quotechar.
        - **escapechar**: Character string to escape the delimiter if 'quoting' is set to 0. If defined, it will also escape/double itself. By default (None), it will not escape the delimiter.
        - **field_size_limit**: maximum field size allowed by the parser. Default "sys.maxsize". Lower the value to skip writing large inputs.

    Current job section:
        - **outfile** (str): *outfile* can be defined in the job section if the outfile in the section is empty
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('file_exists', 'APPEND')
        self.set_default_config('delimiter', ';')
        self.set_default_config('quotechar', '"')
        self.set_default_config('extrasaction', 'raise')
        self.set_default_config('restval', '')
        self.set_default_config('write_header', 'True')
        self.set_default_config('quoting', '2')  # QUOTE_MINIMAL=0, QUOTE_ALL=1, QUOTE_NONNUMERIC=2, QUOTE_NONE=3
        self.set_default_config('doublequote', True)
        self.set_default_config('escapechar', None)
        self.set_default_config('field_size_limit', sys.maxsize)  # Default csv max is 131072

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        csv.field_size_limit(int(self.myconfig('field_size_limit')))
        csvwriter = None
        outputfile = self._outputfile()
        delimiter = self.myconfig('delimiter')
        if delimiter == 'TAB':
            delimiter = '\t'
        # Do not repeat the header if appending results and the file exists
        outfilename = self._get_outfile()
        if self.myconfig('file_exists') == 'APPEND' and outfilename != "CONSOLE" and os.path.exists(outfilename) and os.path.getsize(outfilename):
            write_header = False
        else:
            write_header = self.myflag('write_header')

        for fileinfo in self._source(path):
            if csvwriter is None:
                fieldnames = self.myarray('fieldnames')
                if not fieldnames:
                    fieldnames = fileinfo.keys()
                csvwriter = csv.DictWriter(
                    outputfile,
                    fieldnames=fieldnames,
                    extrasaction=self.myconfig('extrasaction'),
                    restval=self.myconfig('restval'),
                    delimiter=delimiter,
                    quotechar=self.myconfig('quotechar'),
                    quoting=int(self.myconfig('quoting')),
                    escapechar=self.myconfig('escapechar'),
                    doublequote=self.myconfig('doublequote'))
                if write_header:
                    csvwriter.writeheader()
            try:
                csvwriter.writerow(fileinfo)
            except Exception as exc:
                if self.myflag('stop_on_error'):
                    raise
                self.logger().warning(f'Exception while writing to the file: {exc}')

            yield fileinfo

        try:
            if not outputfile == sys.stdout:
                outputfile.close()
        except Exception as exc:
            self.logger().warning(f'Exception while closing the file: {exc}')


class MDTableSink(BaseSink):
    """ A module that prints the results from other modules to a file or standard output as an markdown file with table output. Removes repeated entries.

    Configuration:
        - **outfile** (str): If provided, saved to this file (absolute path) instead of standard output. CONSOLE is a special name: prints to standard output.
        - **file_exists** (str): If outfile exists, APPEND (this is the default behaviour), OVERWRITE or throw an ERROR.
        - **fieldnames** (str): Use these field names as columns. Use this option to order the fields. If not provided, they are taken from first input keys.
        - **backticks_fields** (str): Sorround selected fields with backticks to ensure correct MD visualization.
        - **path_fields** (str): Sorround selected fields with LaTeX path command to ensure correct MD visualization.
        - **first_line** (str): Write a first line before headers.
        - **skip_headers** (bool): If True, do not print table headers. Default=False.
        - **empty_str** (str): String to fill empty fields.
        - **chars_escaped** (str): List of characters to escape.
        - **path_chars_escaped** (str): List of characters to escape only in the 'path_fields', in addition to those set in 'chars_escaped'.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('fieldnames', '')
        self.set_default_config('backticks_fields', '')
        self.set_default_config('path_fields', '')
        self.set_default_config('file_exists', 'APPEND')
        self.set_default_config('first_line', '')
        self.set_default_config('skip_headers', False)
        self.set_default_config('empty_str', '-')
        self.set_default_config('chars_escaped', '|')
        self.set_default_config('path_chars_escaped', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        outputfile = self._outputfile()

        fields = self.myarray('fieldnames')
        backticks_fields = self.myarray('backticks_fields')
        path_fields = self.myarray('path_fields')
        empty_str = self.myconfig('empty_str')
        chars_escaped = self.myarray('chars_escaped')
        escaped_table = str.maketrans({c: '\\' + c for c in chars_escaped})
        path_chars_escaped = self.myarray('path_chars_escaped')
        path_escaped_table = str.maketrans({c: '\\' + c for c in path_chars_escaped})
        skip_headers = self.myflag('skip_headers')
        act = {field: '' for field in fields}
        data_to_compare = act.copy()

        first_line = self.myconfig('first_line')
        if first_line:
            outputfile.write(first_line.replace('\\n', '\n'))
            outputfile.write("\n")

        # Items
        write_header = not skip_headers
        for fileinfo in self._source(path):
            if not fields:
                fields = fileinfo.keys()
                act = {field: '' for field in fields}
                data_to_compare = act.copy()
            if write_header:
                outputfile.write("|".join(fields))
                outputfile.write("\n")
                outputfile.write("|".join(["--"] * len(fields)))
                outputfile.write("\n")
                write_header = False
            try:
                # Exclude consecutive repeated entries
                repeated = True
                for fld in fields:
                    if fileinfo.get(fld, '') != data_to_compare.get(fld, ''):
                        repeated = False
                    act[fld] = fileinfo.get(fld, '')
                    if escaped_table:
                        act[fld] = str(act[fld]).translate(escaped_table)
                    if fld in backticks_fields and fileinfo.get(fld, ''):
                        act[fld] = '`' + act[fld] + '`'
                    if fld in path_fields and fileinfo.get(fld, ''):
                        if path_escaped_table:
                            act[fld] = str(act[fld]).translate(path_escaped_table)
                        act[fld] = r'`\path{' + act[fld] + r'}`{=latex}'
                if repeated:
                    continue
                outputfile.write("|".join([act.get(field, empty_str) for field in fields]))
                outputfile.write("\n")
                data_to_compare = fileinfo.copy()
                yield fileinfo
            except TypeError as exc:
                if self.myflag('stop_on_error'):
                    raise
                else:
                    self.logger().warning('{}: {}'.format(exc, fileinfo.get('path', '')))

        # outputfile.write("\n")  # Prepare room for next table in case appending outputs
        try:
            if not outputfile == sys.stdout:
                outputfile.close()
        except Exception as exc:
            self.logger().warning(f'Exception while closing the file: {exc}')

class DummySink(BaseSink):
    """ A module that prints the results from other modules to a file or standard output.
 
    Configuration:
        - **outfile** (str): If provided, saved to this file (absolute path) instead of standard output. CONSOLE is a special name: prints to standard output.
        - **file_exists** (str): If outfile exists, APPEND (this is the default behaviour), OVERWRITE or throw an ERROR.
    """
 
    def read_config(self):
        super().read_config()
 
    def run(self, path=None):
        self.check_params(path, check_from_module=True)
 
        outputfile = self._outputfile()
 
        for fileinfo in self._source(path):
            try:
                outputfile.write(fileinfo)
                outputfile.write("\n")
                yield fileinfo
            except Exception as exc:
                if self.myflag('stop_on_error'):
                    raise
                else:
                    self.logger().warning('{}: {}'.format(exc, fileinfo.get('path', '')))
 
        try:
            if not outputfile == sys.stdout:
                outputfile.close()
        except Exception as exc:
            self.logger().warning(f'Exception while closing the file: {exc}')

class MirrorPath(base.job.BaseModule):
    """ A basic module that yields the path. """
    def run(self, path):
        yield dict(path=path)
