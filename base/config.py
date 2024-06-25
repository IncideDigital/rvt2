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


""" Classes and helper functions to manage the global, local and job configuration.

Warning:
    Since this module is used to configure the logging system, it cannot log any message.
"""

import os
import os.path
import glob
import configparser
import requests
import logging
import logging.config
from io import StringIO
import csv

# The name of the default section in the configuration file
DEFAULTSECT = configparser.DEFAULTSECT

# How to set colors in a TTY
COLORS = {
    'YELLOW': "\033[1;33m",
    'RED': "\033[1;31m",
    'RED_BG': "\033[41m",
    'BLUE': "\033[1;34m",
    'WHITE': "\033[1;37m",
    'CYAN': "\033[1;36m",
    'GRAY': "\033[90m"
}
# The rest sequence of a TTY
RESET_SEQ = "\033[0m"
# The bold sequence of a TTY
BOLD_SEQ = "\033[1m"


def parse_conf_array(value):
    r""" Parses a value in an option and returns it as an array.

    Values are sepparated using spaces or new lines.
    Double quotes can be used as quoting chars.
    Spaces can be espaced with a backslash.

    >>> parse_conf_array('hello')
    ['hello']

    >>> parse_conf_array('hello world')
    ['hello', 'world']

    >>> parse_conf_array('hello\ world')
    ['hello world']

    >>> parse_conf_array('"hello world" bye')
    ['hello world', 'bye']

    >>> parse_conf_array('base.module.test{"param":"value1\ value2"}')
    ['base.module.test{"param":"value1 value2"}']

    >>> parse_conf_array('base.module.test{"param":"value1\ value2"} base.module.test{"param":"value3\ value4"}')
    ['base.module.test{"param":"value1 value2"}', 'base.module.test{"param":"value3 value4"}']

    >>> parse_conf_array(None)
    []

    >>> parse_conf_array('')
    []

    Args:
        value (str): The value to parse.

    Returns:
        An array of strings.
    """
    if value is not None and value:
        confvalue = StringIO(value.strip().replace('\n', ' '))
        reader = csv.reader(confvalue, delimiter=' ', quotechar='"', escapechar='\\')
        for row in reader:
            # return the first line
            return row
    return []


def configure_logging(config, basic=False):
    """ Configure the logging system. Some variables can be configured from the [logging] section in the configuration.

    Parameters:
        config (config.Config): the global configuration object.
        basic (Boolean): if True, configure a basic but colored logging system to the console.

    Todo:
        We couldn't find a way to configure log filename easily for each case using configuration files.
        Temporally, the logging subsystem is configured using a dictionary and not a configuration file.

    Configuration:
        - *console.level*: The logging level for the console handler. Defaults to WARN.
        - *file.level*: The logging level for the file handler. Defaults to INFO.
        - *file.logfile*: The filename for the file handler. Defaults to rvt2.log.
        - *telegram.level*: The logging level for the telegram handler. Defaults to INFO.
        - *telegram.token*: the token for the telegram bot. Defaults to None (do not send messages)
        - *telegram.chatids*": a space separated list of chatids to send messages.
    """

    # remove existing handlers to reset the system
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)
        h.close()

    logfile = config.get('logging', 'file.logfile', None)

    if not basic and logfile:
        os.makedirs(os.path.dirname(logfile), exist_ok=True)
        logging.config.dictConfig({
            'version': 1,
            'formatters': {
                'brief': {
                    'format': '[%(levelname)s] %(name)s: %(message)s'
                },
                'precise': {
                    'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    'datefmt': '%Y-%m-%d %H:%M:%S'
                },
                'colored': {
                    '()': 'base.config.ColoredFormatter',
                    'format': '%(name)s: %(levelname)s - %(message)s'
                }
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'colored',
                    'level': config.get('logging', 'console.level', 'WARN')
                },
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'level': config.get('logging', 'file.level', 'INFO'),
                    'formatter': 'precise',
                    'filename': logfile
                },
                'telegram': {
                    'level': config.get('logging', 'telegram.level', 'INFO'),
                    'class': 'base.config.TelegramHandler',
                    'chatids': config.get('logging', 'telegram.chatids', ''),
                    'token': config.get('logging', 'telegram.token', ''),
                    'formatter': 'brief'
                }
            },
            'loggers': {
                '': {
                    'handlers': ['console', 'file'],
                    'level': 'DEBUG',
                    'propagate': True
                },
                'analyst': {
                    'handlers': ['telegram'],
                    'level': 'DEBUG',
                },
                # loggers of libraries and external tools used by the RVT
                'dkimpy': {
                    'level': 'CRITICAL'
                },
                'urllib3.connectionpool': {
                    'level': 'ERROR'
                },
                'elasticsearch': {
                    'level': 'ERROR'
                }
            }
        })
    else:
        level = config.get('logging', 'console.level', 'WARN')
        handler = logging.StreamHandler()
        formatter = ColoredFormatter(fmt='%(name)s: %(levelname)s - %(message)s')
        # use color only if we are outputting to a tty
        formatter.use_color = handler.stream.isatty()
        handler.setFormatter(formatter)
        logging.basicConfig(level=level, handlers=[handler])


def check_server(server):
    """ Check whether a server can be reached.

    >>> check_server(None)
    False

    >>> check_server('https://www.google.es')
    False

    >>> check_server('https://www.google.es:443')
    True

    Parameters:
        server (str): a URL to connect to a server, such as "http://localhost:9998".
            **A scheme, hostname and port** must be provided. A malformatted server will return False.
    Returns:
        True is the server is listening
    """
    import socket
    import urllib.parse

    if not server:
        return False
    url = urllib.parse.urlparse(server)
    if not url.hostname:
        return False
    try:
        hostip = socket.gethostbyname(url.hostname)
    except socket.gaierror:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if not url.port:
        return False
    result = sock.connect_ex((hostip, int(url.port)))
    sock.close()
    return result == 0


class MyExtendedInterpolation(configparser.ExtendedInterpolation):
    """ Adds support to inheritance to the extended interpolator.

    When getting the value of an option from a section, if
    the option is not defined in the current section, check
    if the section has an inherits options. If there is
    an inherits options, look for the option in the inherits
    section and then the DEFAULTS section. """
    def before_get(self, parser, section, option, value, defaults):
        inherits_from = parser.get(section, 'inherits', raw=True, fallback=None)
        if inherits_from:
            # add the values in the inherited section to the defaults dictionary
            defaults = dict(defaults)
            defaults.update(parser[inherits_from])
        return super().before_get(parser, section, option, value, defaults)


class Config:
    """ Configuration of modules and jobs.
    It is a wrapper on configparser.SafeConfigParser object.

    Parameters:
        filenames (array of str): if not None, read configuration from these files
        job_name (str): The name of the job currently in execution.
        config (configparser.SafeConfigParser): the actual configuration object.

    Attributes:
        config (configparser.SafeConfigParser): the actual configuration object.
    """
    def __init__(self, filenames=None, config=None, job_name=None):
        if config is None:
            self.config = configparser.ConfigParser(interpolation=MyExtendedInterpolation())
            # Add support to a few addition Trur/False words
            self.config.BOOLEAN_STATES = {
                '1': True, 'true': True, 'TRUE': True, 'True': True, 'ON': True, 'on': True,
                '0': False, 'false': False, 'FALSE': False, 'False': False, 'OFF': False, 'off': False,
            }
        else:
            self.config = config
        self.job_name = job_name
        # a place holder to save a localStore object
        self.__localStore = None
        self.__localStore_is_dirty = False

        if filenames:
            for fn in filenames:
                self.read(fn)

    def get(self, section, option, default=None):
        """ Get a configuration value.

        Parameters:
            section (str): name of the section.
            option (str): name of the option
            default (Object): if not None, the default value to return.

        Returns:
            The value of the option.
        """
        if not self.config.has_section(section):
            return self.config[DEFAULTSECT].get(option, default)
        value = self.config[section].get(option, None)
        if value is None:
            inheritance = self.config[section].get('inherits', None)
            if inheritance is not None:
                try:
                    return self.config[inheritance].get(option, default)
                except KeyError:
                    raise KeyError('Section {} tries to inherit from non-existent section: {}'.format(section, inheritance)) from None
            return default
        return value

    def get_boolean(self, section, option, default=False):
        """ A convenience method for boolean options """
        value = self.get(section, option, str(default))
        return value in ('True', 'true', 'TRUE', 1)

    def read(self, path, pattern='**/*.cfg'):
        """ Read configuration from a file or directory. The configuration file is appended to the current configuration.

        Parameters:
            path (str): The path of the single file or directory to read the configuration from.
            pattern (regex): If the path is a directory, use this pattern to select configuration files.
        """
        if os.path.isdir(path):
            for conffile in glob.iglob(os.path.join(path, pattern), recursive=True):
                self.read(conffile)
        else:
            self.config.read(path)

    def copy(self):
        """ Returns a deep copy of this configuration object """
        import pickle
        # deep copy of a configparser using ExtendedInterpolator
        # See https://stackoverflow.com/questions/23416370/manually-building-a-deep-copy-of-a-configparser-in-python-2-7
        rep = pickle.dumps(self.config)
        new_config = pickle.loads(rep)
        return Config(config=new_config, job_name=self.job_name)

    def has_section(self, section):
        """ Return True if the configuration has a section """
        return self.config.has_section(section)

    def sections(self):
        """ Returns a list of sections in this config """
        return self.config.sections()

    def options(self, section):
        """ Return the options in a section """
        if self.has_section(section):
            return self.config.options(section)
        return []

    def set(self, section, option, value):
        """ Add a configuration to a section. If the section does not exists, add it. """
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config[section][option] = value

    def store_get(self, option, default, job_name=None):
        """ Read and returns an option from the local store.

        A *local store* can be used to save and retrieve options between runnings or communicate modules in
        in the save job. Do not rely on these options to exist and always use a default value.

        The local store is saved optionally in the file configured in section *job_name*, option *localstore*.
        Options are saved in a section named after the current *job_name*. Notice you can read from any job_name, but only save
        options on your own job_name.

        Parameters:
            option: the name of the option
            default: the default value of the option. Do not rely on these options to exist an always use a default value.
            job_name: if provided, read the option from this job_name.
        """
        if job_name is None:
            job_name = self.job_name
        if self.__localStore is None:
            # if the localstore is not yet created, create it without interpolation
            self.__localStore = configparser.ConfigParser(interpolation=None)
            localstorefilename = self.get(self.job_name, 'localstore', None)
            # if the localstorefile exists, read localstore from it
            if localstorefilename and os.path.exists(localstorefilename):
                self.__localStore.read(localstorefilename)
        # return the option
        if not option or not self.__localStore.has_section(job_name):
            return default
        return self.__localStore[job_name].get(option, default)

    def store_set(self, option=None, value=None, save=False):
        """ Store an option from the local store.

        A *local store* can be used to save and retrieve options between runnings or communicate modules in
        in the save job. Do not rely on these options to exist and always use a default value.

        The local store is saved optionally in the file configured in section *job_name*, option *localstore*.
        Options are saved in a section named after the current *job_name*. Notice you can read from any job_name, but only save
        options on your own job_name.

        Parameters:
            option (str): the name of the option. If ``None``, do not store an option. The local store can be saved id ``option=None`` and ``save=True``.
            value (str): the value of the option. If ``None``, remove the option.
            save (Boolean): whether the local store must be saved inmediately in the file configured in section *job_name*, option *localstore*.
                If there is no file configured, do not save the localstore. If the localStore was not dirty, it is not saved.
        """
        # if the localstore is not created, read the option once
        if self.__localStore is None:
            self.store_get(option, None)
        # save the option
        if option is not None:
            # Add the section if it does not exist
            if not self.__localStore.has_section(self.job_name):
                self.__localStore.add_section(self.job_name)
            # Add or remove the option
            if value is None:
                self.__localStore.remove_option(self.job_name, option)
            else:
                self.__localStore[self.job_name][option] = str(value)
            self.__localStore_is_dirty = True
        # save the local store if save = True
        if save and self.__localStore_is_dirty:
            localstorefilename = self.get(self.job_name, 'localstore', None)
            if localstorefilename:
                try:
                    with open(localstorefilename, 'w') as localstorefile:
                        self.__localStore.write(localstorefile)
                    self.__localStore_is_dirty = False
                except Exception:
                    # ignore errors
                    pass


class ColoredFormatter(logging.Formatter):
    """ A formatter with colors for the logging system.

    Based on ideas from: <https://stackoverflow.com/questions/384076/how-can-i-color-python-logging-output> and <https://github.com/borntyping/python-colorlog>

    Attributes:
        use_color (Boolean): If True, use color on the output. If False, this formatters is the same than a regular Formatter.
    """

    __COLOR_LEVELS = {
        'WARNING': COLORS['YELLOW'],
        'INFO': COLORS['WHITE'],
        'DEBUG': COLORS['CYAN'],
        'CRITICAL': COLORS['RED_BG'],
        'ERROR': COLORS['RED']
    }

    use_color = True

    def format(self, record):
        if self.use_color:
            original = dict(msg=record.msg, levelname=record.levelname, name=record.name)
            levelname = record.levelname
            record.msg = self.__COLOR_LEVELS[levelname] + str(record.msg) + RESET_SEQ
            record.levelname = COLORS['GRAY'] + record.levelname + RESET_SEQ
            record.name = COLORS['BLUE'] + record.name + RESET_SEQ
            message = super().format(record)
            # recover the original values of these parameters
            record.levelname = original['levelname']
            record.name = original['name']
            record.msg = original['msg']
        else:
            message = super().format(record)
        return message


class TelegramHandler(logging.Handler):
    """ A logging handler to send messages to a list of telegram chatids """
    def __init__(self, level=logging.INFO, token='', chatids=''):
        super().__init__(level)
        self.chatids = parse_conf_array(chatids)
        self.token = token

    def emit(self, record):
        msg = self.format(record)
        if self.token and self.chatids:
            for chatid in self.chatids:
                try:
                    requests.get('https://api.telegram.org/bot{}/sendMessage'.format(self.token), data=dict(chat_id=chatid, text=msg))
                except Exception:
                    pass


default_config = Config()
