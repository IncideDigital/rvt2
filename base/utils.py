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

""" Utility functions to the rest of the system. """

import os
import base.job
import base.config
import shutil
import uuid

__maintainer__ = 'Juanvi Vera'


def check_folder(path):
    """ Check is a path is a folder and create if not exists.

    Equivalent to ``check_directory(path, create=True)``
    """
    check_directory(path, create=True)


def check_directory(path, create=False, delete_exists=False, error_exists=False, error_missing=False):
    """ Check if a directory exists.

    Parameters:
        error_exists (Boolean): If True and the directory exits, raise a RVTError
        error_missing (Boolean): If True and the file does not exist, raise a RVTError
        create (Boolean): If True and the directory does not exist, create it
        delete_exists (Boolean): If True, delete the directory and create a new one.

    Returns:
        True if the directory exists at the end of this function.
    """
    if os.path.exists(path):
        if error_exists:
            raise base.job.RVTError('{} exists'.format(path))
        if not os.path.isdir(path):
            raise base.job.RVTError('{} exists and it is not a directory'.format(path))
        if delete_exists:
            shutil.rmtree(path)
    else:
        if error_missing:
            raise base.job.RVTError('{} does not exist'.format(path))
    if create:
        os.makedirs(path, exist_ok=True)
    return os.path.exists(path)


def check_file(path, error_missing=False, error_exists=False, delete_exists=False, create_parent=False):
    """ Check if a file exists, and optionally removes it.

    Parameters:
        error_exists (Boolean): If True and the file exists, raise a RVTError
        error_missing (Boolean): If True and the file does not exist, raise a RVTError
        delete_exists (Boolean): If True, delete the file if exists
        create_parent (Boolean): If True, create the parent directory

    Raises:
        RVTError if the path is not a file, or the file does not exist and error_exists is set to True

    Returns:
        True if the file exists at the end of this function.
    """
    if os.path.exists(path):
        if error_exists:
            raise base.job.RVTError('{} exists'.format(path))
        if not os.path.isfile(path):
            raise base.job.RVTError('{} exists and it is not a file'.format(path))
        if delete_exists:
            os.remove(path)
    else:
        if error_missing:
            raise base.job.RVTError('{} does not exist'.format(path))
    if create_parent:
        check_directory(os.path.dirname(path), create=True)
    return os.path.exists(path)


def relative_path(path, start):
    """
    Transform a path to be relative to a start path.

    Todo:
        We don't want to go outside the starting path. Check that.

    Returns:
        path relative to start path.

    >>> relative_path('/morgue/112234-casename/01/23', '/morgue/112234-casename')
    '01/23'
    >>> relative_path('/another/112234-casename/01/23', '/morgue/112234-casename')
    '../../another/112234-casename/01/23'
    >>> relative_path(None, '/morgue/11223344-casename') is None
    True
    """
    try:
        return os.path.normpath(os.path.relpath(path, start=start))
    except ValueError:
        return None


def save_csv(data, config=None, **kwargs):
    """
    Save data in a CSV file. This is a convenient function to run a ``base.output.CSVSink`` module from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        kwargs (dict): The extra configuration for the `base.output.CSVSink` module. You'd want to set, at least, `outfile`.
    """
    if config is None:
        config = base.config.Config()
    m = base.job.load_module(
        config, 'base.output.CSVSink',
        extra_config=kwargs,
        from_module=data
    )
    list(m.run())


def save_json(data, config=None, **kwargs):
    """
    Save data in a JSON file. This is a convenient function to run a ``base.output.JSONSink`` module from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        kwargs (dict): The extra configuration for the `base.output.JSONSink` module. You'd want to set, at least, `outfile`.
    """
    if config is None:
        config = base.config.Config()
    m = base.job.load_module(
        config, 'base.output.JSONSink',
        extra_config=kwargs,
        from_module=data
    )
    list(m.run())


def generate_id(data=None):
    """ Generate a unique ID for a piece of data. If data is None, returns a random indentifier.

    The identifier is created using::

        uuid.uuid5(uuid.NAMESPACE_URL, 'file:///{}/{}?{}'.format(dirname, filename, embedded_path))

    If the data already provides and identifier in an field ``_id``, pop this field from data and return it.
    """

    if not data:
        return uuid.uuid4()

    if '_id' in data:
        return data.pop('_id')

    dirname = data.get('dirname', None)
    if dirname is not None:
        dirname = dirname.encode(errors='backslashreplace').decode()
    filename = data.get('filename', None)
    if filename is not None:
        filename = filename.encode(errors='backslashreplace').decode()
    embedded_path = data.get('embedded_path', None)
    if embedded_path is not None:
        embedded_path = embedded_path.encode(errors='backslashreplace').decode()
    if dirname and filename:
        if embedded_path:
            return uuid.uuid5(uuid.NAMESPACE_URL, 'file:///{}/{}?{}'.format(dirname, filename, embedded_path))
        else:
            return uuid.uuid5(uuid.NAMESPACE_URL, 'file:///{}/{}'.format(dirname, filename))
    else:
        # not enough information: random ID
        return uuid.uuid4()
