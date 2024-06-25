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
import shutil
import uuid
import hashlib
import json
import re
import logging
import base.job
import base.config
import datetime
import pytz
import dateutil.parser
from functools import lru_cache
from pathlib import Path, PureWindowsPath

# ----------------------------
# PATH MANAGEMENT
# ----------------------------

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
    try:
        exists = os.path.lexists(path)
        valid_path = True
    except TypeError:
        exists = False
        valid_path = False

    if exists:
        if error_exists:
            raise base.job.RVTError('{} exists'.format(path))
        if not (os.path.isfile(path) or os.path.islink(path)):
            raise base.job.RVTError('{} exists and it is not a file'.format(path))
        if delete_exists:
            os.remove(path)
    else:
        if error_missing:
            raise base.job.RVTError('{} does not exist'.format(path))
    if create_parent and valid_path:
        check_directory(os.path.dirname(path), create=True)
    return exists


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


def windows_format_path(path, enclosed=False):
    """ Return a Windows format path. If 'enclosed', sorround by semicolons so shlex or other functions can process the full path as one """
    path = str(PureWindowsPath(Path(path)))
    if enclosed:
        return '"' + path + '"'
    return path


# ----------------------------
# OUTPUT MANAGEMENT
# ----------------------------

def save_output(data, config=None, output_module='base.output.CSVSink', **kwargs):
    """
    Save data in some standard output format file. This is a convenient function to run a ``base.output`` modules from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        output_module (str): Name of the output module. Ex: 'base.output.CSVSink'
        kwargs (dict): The extra configuration for the `base.output` module. You'd want to set, at least, `outfile`.
    """
    if config is None:
        config = base.config.default_config
    m = base.job.load_module(
        config, output_module,
        extra_config=kwargs,
        from_module=data
    )
    list(m.run())


def save_csv(data, config=None, **kwargs):
    """
    Save data in a CSV file. This is a convenient function to run a ``base.output.CSVSink`` module from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        kwargs (dict): The extra configuration for the `base.output.CSVSink` module. You'd want to set, at least, `outfile`.
    """
    save_output(data, config, 'base.output.CSVSink', **kwargs)

def save_dummy(data, config=None, **kwargs):
    """
    Save data in a file. This is a convenient function to run a ``base.output.DummySink`` module from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        kwargs (dict): The extra configuration for the `base.output.CSVSink` module. You'd want to set, at least, `outfile`.
    """
    save_output(data, config, 'base.output.DummySink', **kwargs)


def save_json(data, config=None, **kwargs):
    """
    Save data in a JSON file. This is a convenient function to run a ``base.output.JSONSink`` module from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        kwargs (dict): The extra configuration for the `base.output.JSONSink` module. You'd want to set, at least, `outfile`.
    """
    save_output(data, config, 'base.output.JSONSink', **kwargs)


def save_md_table(data, config=None, **kwargs):
    """
    Save data in a markdown file. This is a convenient function to run a ``base.output.MDTableSink`` module from inside another module.

    Parameters:
        data: The data to be saved. It can be a generator (such as list or tuple) or a `base.job.BaseModule`. In the last case, the module is run and saved.
        config (base.config.Config): The global configuration object, or None to use default configuration.
        kwargs (dict): The extra configuration for the `base.output.CSVSink` module. You'd want to set, at least, `outfile`.
    """
    save_output(data, config, 'base.output.MDTableSink', **kwargs)


# ----------------------------
# ID AND HASH GENERATION
# ----------------------------

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


def generate_hash(data=None, algorithm='md5'):
    """ Generate a hash (MD5 by default) for a dictionary. If data is None, returns a random indentifier.

    The identifier is created using the encoded input data.

    If the data already provides and identifier in an field ``_id``, pop this field from data and return it.
    """

    if not data:
        return uuid.uuid4()

    if '_id' in data:
        return data.pop('_id')

    dhash = _select_hash_algorithm(algorithm)
    encoded = json.dumps(data, sort_keys=True).encode()
    dhash.update(encoded)
    return dhash.hexdigest()


def get_filehash(filepath, sha=None, algorithm='sha256'):
    """ Calculates or updates the hash (SHA256 by default) of a file """
    # Specify how many bytes of the file you want to open at a time
    BLOCKSIZE = 65536

    # Take the input sha if provided, or create a new one
    digest = False
    if not sha:
        digest = True
        sha = _select_hash_algorithm(algorithm)

    with open(filepath, 'rb') as f:
        file_buffer = f.read(BLOCKSIZE)
        while len(file_buffer) > 0:
            sha.update(file_buffer)
            file_buffer = f.read(BLOCKSIZE)
    if digest:
        return sha.hexdigest()
    else:
        return sha


def _select_hash_algorithm(name='sha256'):
    "Return hashlib object with the desired algorithm"
    algorithms = {'sha1': hashlib.sha1(),
                  'sha256': hashlib.sha256(),
                  'sha512': hashlib.sha512(),
                  'md5': hashlib.md5(),}
    if name.lower() not in algorithms:
        logging.warning(f'Selected hash algorithm name "{name}" not supported. Available options: {algorithms.keys()}. Taking default algorithm sha256')
        name = 'sha256'
    return algorithms[name]

# ----------------------------
# IP MANAGEMENT
# ----------------------------

def sanitize_ip(value):
    """ Adapt IP fields to Elastic IPv4 or IPv6 addresses format (see https://www.elastic.co/guide/en/elasticsearch/reference/current/ip.html)

    Possible inputs to convert:
    - ''                        --> null (Ipfield throws error when processing empty string)
    - `-`                       --> null
    - LOCAL                     --> ::1
    - [123.123.123.123]         --> 123.123.123.123
    - ::ffff:10.100.1.87        --> 10.100.1.87 (Revert the default IPv4toIPv6 convention to simplify reading)
    - 123.123.123.123::1980     --> ip=123.123.123.123, port=1980 (Ports are treated as separated field)
    - ::1234:5678:1.2.3.4:443   --> ip=::1234:5678:1.2.3.4, port=443
    - [2603:10a6:7:94:cafe::d6]:3 --> ip=2603:10a6:7:94:cafe::d6, port=3
    - 123.123.123.123           --> 123.123.123.123 (Valid IPv4 format. No changes)
    - 2001:db8:1::ab9:C0A8:102  --> 2001:db8:1::ab9:C0A8:102 (Valid IPv6 format. No changes)
    - ::1234:5678:1.2.3.4       --> ::1234:5678:1.2.3.4 (Valid dual IPv6 format. No changes)

    Any other escenario will return null as IP value.

    Returns tuple (ip, port)
    """

    if not value or value == '-':
        return (None, None)
    if value.lower().startswith('local'):
        return ('::1', None)

    # Regular expression to match IPv4 or Ipv6 address and optional port
    ip_pattern = re.compile(r'^\[?(?P<ip>.*?)\]?(?::(?P<port>\d+))?$')
    # Regular expression to match IPv6 address and optional port. If port included, "[]" brackets are mandatory
    if ']' in value:
        ipv6_pattern = re.compile(r'^\[(?P<ip>.*?)\](?::(?P<port>\d+))?$')
    else:
        ipv6_pattern = re.compile(r'^(?P<ip>.*?)(?P<port>$)')

    match = ip_pattern.match(value)
    if not match:
        return (None, None)
    ip = match.group('ip')
    port = check_integer(match.group('port'))

    # Case when an IPv4 is included. Prioritize over IPv6
    if '.' in ip:
        terms = ip.rstrip(':').split(':')
        ipv4 = terms[-1]
        ipv6 = ':'.join(terms[:-1])
        valid_v4 = False
        if is_valid_ipv4_address(ipv4):
            valid_v4 = True
        else:
            logging.debug(f'IP value "{value}" is not a valid IPv4')
        if not is_valid_ipv6_address(ipv6) and not valid_v4:
            logging.warning(f'IP value "{value}" is not a valid IP')
            return (None, None)
        return (ipv4 if valid_v4 else ipv6, port)

    # Only IPv6 case
    else:
        match_ipv6 = ipv6_pattern.match(value)
        ip = match_ipv6.group('ip')
        port = check_integer(match_ipv6.group('port'))
        if not is_valid_ipv6_address(ip):
            logging.warning(f'IP value "{value}" is not a valid IPv6')
            return (None, None)
        return (ip, port)


def is_valid_ipv4_address(address):
    # Regular expression pattern for a valid IPv4 address
    pattern = r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'

    if re.match(pattern, address):
        return True
    else:
        return False


def is_valid_ipv6_address(address):
    # Regular expression pattern for a valid IPv6 address
    pattern = r'^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$'

    if re.match(pattern, address):
        return True
    else:
        return False


def check_integer(value):
    """ Check if an object can be casted to an integer. Return the casted object or None. """
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

# ----------------------------
# DATE MANAGEMENT
# ----------------------------

def date_to_iso(source, input_timezone="UTC", output_timezone="UTC", on_fail='NULL', dayfirst=False, sep="T", timespec='auto', hide_tz=False):
    """ Get input data representing a date and return a string in ISO format. Both input and output timezones are editable. """
    dt = to_localized_date(source, tz_name=input_timezone, dayfirst=dayfirst, on_fail=on_fail)
    return convert_to_iso(dt, sep=sep, timespec=timespec, tz_name=output_timezone, hide_tz=hide_tz, on_fail=on_fail)


def to_localized_date(source, tz_name='UTC', dayfirst=False, on_fail='NULL'):
    """ Convert a date to a localized datetime object.
        Admit either an epoch timestamp, a date string or a non localized datetime object as an input.
        If `source` does not provided a timezone, assign tz_name.
    """
    if not source or source == "-":
        return _on_fail_dates(on_fail_condition=on_fail.upper(), output_type='DATETIME')
    try:
        # Timestamp input
        if type(source) == int or (type(source) == str and source.isdigit()):
            dt = datetime.datetime.fromtimestamp(int(source), datetime.timezone.utc)
        # Datetime input
        elif type(source) == datetime.datetime:
            dt = source
        # String input            
        else:
            # WARNING: dateutil uses American notation when in doubt: 09/03/2022 is September 3rd
            # Using dayfirst parameter enforces European notation, but fails interpreting ISO format
            dt = dateutil.parser.parse(source, dayfirst=dayfirst)
    except Exception as exc:
        logging.warning(f'Problems parsing input date {source}. {exc}')
        return _on_fail_dates(on_fail_condition=on_fail.upper(), output_type='DATETIME')

    # Set the timezone:
    try:
        if dt.tzinfo:
            # Take the original timezone if included in source, no matter what tz_name is set
            return dt
        tz = pytz.timezone(tz_name)
    except Exception as exc:
        logging.warning(f'Input timezone provided is not valid: {tz_name}. Time will be treated as UTC')
        return dt.replace(tzinfo=pytz.utc)
    try:
        localized_datetime = tz.localize(dt)
        return localized_datetime
    except Exception as exc:
        logging.warning(f'Problems setting datezone {tz_name}. {exc}')
        return _on_fail_dates(on_fail_condition=on_fail.upper(), output_type='DATETIME')


def convert_to_iso(source_datetime, sep='T', timespec='auto', tz_name='UTC', hide_tz=False, on_fail='NULL'):
    """ Given a datetime object (source_datetime), return a string representing the date in ISO format adapted to the desired timezone output"""
    try:
        tz = pytz.timezone(tz_name)
    except Exception as exc:
        logging.warning(f'Output timezone provided is not valid: {tz_name}. Time {source_datetime} will be expressed in UTC')
        tz = pytz.utc

    if type(source_datetime) != datetime.datetime:
        #logging.debug(f'Expected a datetime object as input. Input provided: {source_datetime}')
        return _on_fail_dates(on_fail_condition=on_fail.upper(), output_type='ISO', tz_name=tz_name, sep=sep, timespec=timespec, hide_tz=hide_tz)

    try:
        # Convert the datetime to the specified timezone
        dt = source_datetime.astimezone(tz)
        dt = dt.replace(tzinfo=dt.tzinfo if not hide_tz else None)
        # Display in isoformat
        return dt.isoformat(sep=sep, timespec=timespec)
    except Exception as exc:
        logging.warning(f'Problems converting date {source_datetime} to ISO format. {exc}')
        return _on_fail_dates(on_fail_condition=on_fail.upper(), output_type='ISO', tz_name=tz_name, sep=sep, timespec=timespec, hide_tz=hide_tz)


@lru_cache
def _on_fail_dates(on_fail_condition='EPOCH', output_type='DATETIME', tz_name='UTC', sep='T', timespec='auto', hide_tz=False):
    """ Return default common dates. Auxiliar function for `to_localized_date` and `convert_to_iso`. """
    # Case datetime output
    utc_tz = pytz.timezone('UTC')
    on_fail_datetime = {'EPOCH': utc_tz.localize(datetime.datetime.fromtimestamp(0)),
                        'NOW': datetime.datetime.now(datetime.timezone.utc),
                        'NULL': None}
    if output_type.upper() == 'DATETIME':
        return on_fail_datetime.get(on_fail_condition.upper(), None)

    # Case ISO string output
    try:
        tz = pytz.timezone(tz_name)
    except Exception as exc:
        tz = pytz.utc
    on_fail_iso = {'EPOCH': on_fail_datetime['EPOCH'].astimezone(tz),
                   'NOW': on_fail_datetime['NOW'].astimezone(tz),
                   'NULL': ""}  
    for condition in ['EPOCH', 'NOW']:
        on_fail_iso[condition] = on_fail_iso[condition].replace(tzinfo=on_fail_iso[condition].tzinfo if not hide_tz else None).isoformat(sep=sep, timespec=timespec)
    return on_fail_iso.get(on_fail_condition.upper(), "")


def parse_microsoft_timestamp(timestamp):
    """ Converts a Microsoft format timestamp to a datetime object.

    Microsoft file time is a 64-bit value that represents the number of 100-nanosecond intervals
    that have elapsed since 12:00 A.M. January 1, 1601 Coordinated Universal Time (UTC).
    UNIX time is specified as the number of seconds since January 1, 1970.
    There are 134,774 days (or 11,644,473,600 seconds) between these dates.
    """
    unix_time = float(timestamp) *1e-7 - 11644473600
    return datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc)


# ----------------------------
# OTHER
# ----------------------------

def human_readable_size(num):
    """ Converts bytes to human readable magnitudes """

    for unit in ['', 'K', 'M', 'G', 'T', 'P']:
        if abs(num) < 1024.0:
            return "%3.1f%s" % (num, unit)
        num /= 1024.0
    return "%.1f%s" % (num, 'Yi')
