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


""" Some simple file readers to be used as input for other modules. """

import csv
import sqlite3
import json
import sys
from tqdm import tqdm

import base.job
from base.config import parse_conf_array
from base.commands import estimate_iterations


class DummyReader(base.job.BaseModule):
    """ A dummy reader that creates as many empty dictionaries as requested in _number_.

    Use for debugging.

    Configuration:
        - **number**: Yields this many of empty dictionaries
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('number', '10')

    def run(self, path):
        """ path and from_module are ignored """
        for i in range(0, int(self.myconfig('number'))):
            yield dict()


class GeneratorReader(base.job.BaseModule):
    """
    Manages `from_module` as a generator, not a module, and yields it contents.

    You can use this module to inject an array into another module down in the chain.

    Example:
        Save a list in a CSV file::

            data = [
                dict(greeting='Hello', language='English'),
                dict(greeting='Hola', language='Spanish')
            ]
            base.output.CSVSink(
                config,
                from_module=GeneratorReader(config, from_module=data),
                local_config=dict(outfile='outfile.csv')
            ).run()

    Attributes:
        from_module: Any generator-like object such a list. Yields its contents.
    """
    def run(self, path=None):
        """ Path is ignored. """
        self.check_params(path, check_from_module=True)
        for data in self.from_module:
            yield data


class AllLinesInFile(base.job.BaseModule):
    """ Yields every line in a file as a string

    Configuration:
        - **encoding** (String): The encoding to use. Defaults to utf-8
        - **progress.disable** (Boolean): If True, disable the progress bar.
        - **progress.cmd** (String): The shell command to run to estimate the number of lines in the file. """

    def read_config(self):
        super().read_config()
        self.set_default_config('encoding', 'utf-8')
        self.set_default_config('progress.disable', 'False')
        self.set_default_config('progress.cmd', 'cat "{path}" | wc -l')

    def run(self, path):
        """ Read all lines from the path. from_module is ignored """
        self.check_params(path, check_path=True, check_path_exists=True)
        total_iterations = base.commands.estimate_iterations(path, self.myconfig('progress.cmd'))
        with open(path, 'r', encoding=self.myconfig('encoding')) as infile:
            for line in tqdm(infile, total=total_iterations, desc=self.section, disable=self.myflag('progress.disable')):
                yield line.strip()


class ForAllLinesInFile(base.job.BaseModule):
    """ Pass to from_module each line in a file as the path.

    Configuration:
        - **encoding** (String): The encoding to use. Defaults to utf-8
        - **progress.disable** (Boolean): If True, disable the progress bar.
        - **progress.cmd** (String): The shell command to run to estimate the number of lines in the file.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('encoding', 'utf-8')
        self.set_default_config('progress.disable', 'False')
        self.set_default_config('progress.cmd', 'cat "{path}" | wc -l')

    def run(self, path):
        """ Read all lines from the path and pass them to from_module """
        self.check_params(path, check_path=True, check_path_exists=True, check_from_module=True)
        total_iterations = base.commands.estimate_iterations(path, self.myconfig('progress.cmd'))
        with open(path, 'r', encoding=self.myconfig('encoding')) as infile:
            for line in tqdm(infile, total=total_iterations, desc=self.section, disable=self.myflag('progress.disable')):
                newpath = line.strip()
                if not newpath:
                    continue
                for data in self.from_module.run(newpath):
                    yield data


class JSONReader(AllLinesInFile):
    """ Load every line in a file as a JSON dictionary and yields it."""

    def run(self, path):
        """ Read JSON file in the path. from_module is ignored """
        self.check_params(path, check_path=True, check_path_exists=True)
        for line in super().run(path):
            try:
                data = json.loads(line.strip())
                yield data
            except json.decoder.JSONDecodeError:
                if self.myflag('stop_on_error'):
                    raise


class CSVReader(base.job.BaseModule):
    """ Yields every line in a CSV file.

    Configuration:
        - **encoding** (String): The encoding to use. Defaults to "utf-8"
        - **delimiter** (String): The delimiter to use. Defaults to ;
        - **quotechar** (String): The quotechar. Defaults to \"
        - **restkey** (String): The restkey of the DictReader. Defaults to "extra".
        - **restval** (String): The restval of the DictReader. Defaults to the empty string.
        - **content_type**: The content_type to set, if fill_common_fields is set
        - **fieldnames**: A space separated list of header names. If None, use the first line.
          Warning: if provided, the first line will be considered data unless ignore_lines is set to >0
        - **ignore_lines** (int): Ignore this numner of initial lines. If fieldnames is provided, the first line is also ignored.
        - **progress.disable** (Boolean): If True, disable the progress bar.
        - **progress.cmd** (String): The shell command to run to estimate the number of lines in the file.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('encoding', 'utf-8')
        self.set_default_config('delimiter', ';')
        self.set_default_config('quotechar', '"')
        self.set_default_config('restkey', 'extra')
        self.set_default_config('restval', '')
        self.set_default_config('fieldnames', '')
        self.set_default_config('ignore_lines', '0')
        self.set_default_config('content_type', '')
        self.set_default_config('progress.disable', 'False')
        self.set_default_config('progress.cmd', 'cat "{path}" | wc -l')
        self.set_default_config('field_size_limit', sys.maxsize)  # Default csv max is 131072

    def run(self, path):
        """ Read CSV file in the path. from_module is ignored """
        self.check_params(path, check_path=True, check_path_exists=True)
        csv.field_size_limit(int(self.myconfig('field_size_limit')))
        with open(path, 'r', encoding=self.myconfig('encoding')) as infile:
            ignore_lines = int(self.myconfig('ignore_lines'))
            fieldnames = (parse_conf_array(self.myconfig('fieldnames')) or None)
            for i in range(0, ignore_lines):
                infile.readline()
            reader = csv.DictReader(
                infile,
                fieldnames=fieldnames,
                restval=self.myconfig('restval'), restkey=self.myconfig('restkey'),
                delimiter=self.myconfig('delimiter'), quotechar=self.myconfig('quotechar'))
            # progress management
            total_iterations = estimate_iterations(path, self.myconfig('progress.cmd'))
            # if fieldnames is None, the first line is header. Add one to progress
            if fieldnames:
                initial_progress = ignore_lines
            else:
                initial_progress = ignore_lines + 1
            # main loop
            for data in tqdm(reader, total=total_iterations, initial=initial_progress, desc=self.section, disable=self.myflag('progress.disable')):
                yield data


def _dict_factory(cursor, row):
    """ A factory to convert cursor rows in a database to dictionaries.

    See Python docs: https://docs.python.org/3.7/library/sqlite3.html """
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class SQLiteReader(base.job.BaseModule):
    """ Returns the cursor of a query on a sqlite database.

    Rows in the database are returned as dictionaries.

    Configuration:
        - **query**: The SQL query to run.

    Current job section:
        - **query**: If the query in the module section is empty, read the SQL query from the job section.
        - **read_only**: If True, open the database in read_only mode
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('query', '')
        self.set_default_config('read_only', False)

    def run(self, path):
        """ Read database from the path. from_module is ignored """
        self.check_params(path, check_path=True, check_path_exists=True)

        query = self.myconfig('query')
        if not query:
            try:
                query = self.config.get(self.config.job_name, 'query', None)
            except Exception as exc:
                self.logger().error('Cannot decode query for section %s: %s', self.section, str(exc))
            if not query:
                self.logger().error('A query must be provided')
                raise base.job.RVTError('A query must be provided')

        connect_args = {'database': path}
        if self.myflag('read_only'):
            path = "file://{}?mode=ro&immutable=1".format(path)
            connect_args = {'database': path, 'uri': True}

        self.logger().info('Query: %s', query)

        with sqlite3.connect(**connect_args) as conn:
            conn.row_factory = _dict_factory
            c = conn.cursor()
            for data in c.execute(query):
                yield data
