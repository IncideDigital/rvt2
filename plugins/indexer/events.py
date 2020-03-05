#!/usr/bin/env python3
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

import os
import datetime
import dateutil.parser
import urllib.parse
from os.path import splitext
import base.job


# ECS Reference: https://www.elastic.co/guide/en/ecs/current/ecs-field-reference.html
# There are 4 categorization fields for events: event.kind, event.category, event.type, event.outcome
# At least the first 3 should be defined for every event


def to_date(strtimestamp):
    """ Converts a timestamp string in UNIX into a date """
    return datetime.datetime.utcfromtimestamp(int(strtimestamp)).isoformat()


def to_iso_format(timestring):
    """ Converts a date string into iso format date """
    if not timestring:
        return datetime.datetime.utcfromtimestamp(0).isoformat()
    try:
        return datetime.datetime.strptime(timestring, '%Y-%m-%d %H:%M:%S').isoformat()
    except Exception:
        try:
            return datetime.datetime.strptime(timestring, '%Y-%m-%d T%H:%M:%SZ').isoformat()
        except Exception:
            return dateutil.parser.parse(timestring).isoformat()


def permissions_to_octal(tsk_permisssion):
    """ Convert a tsk permission string to octal format """
    equivalence = {
        "---": "0",
        "--x": "1",
        "-w-": "2",
        "-wx": "3",
        "r--": "4",
        "r-x": "5",
        "rw-": "6",
        "rwx": "7"
    }
    permission = ['0'] * 4
    try:
        permission[1] = equivalence[tsk_permisssion[-9:-6]]
        permission[2] = equivalence[tsk_permisssion[-6:-3]]
        permission[3] = equivalence[tsk_permisssion[-3:]]
        return ''.join(permission)
    except KeyError:
        return '0000'
    return permission


def filetype(tsk_permisssion):
    """ Get file type from a tsk permission string """
    # File mode by tsk: https://wiki.sleuthkit.org/index.php?title=Fls
    types = {
        "-": "unknown",
        "r": "file",
        "d": "dir",
        "c": "character",
        "b": "block",
        "l": "symlink",
        "p": "fifo",
        "s": "shadow",
        "h": "socket",
        "w": "whiteout",
        "v": "Virtual"
    }
    return types.get(tsk_permisssion[0], 'unknown')


def decompose_url(full_url):
    """ Returns a dictionary with multiple fields for a full url using Elastic Common Schema """
    new_fields = {}
    url_fields = {'scheme': 'url.scheme', 'netloc': 'url.domain', 'path': 'url.path',
                  'query': 'url.query', 'fragment': 'url.fragment', 'username': 'url.username',
                  'password': 'url.password', 'port': 'url.port'}
    url = urllib.parse.urlparse(full_url)

    for k, v in zip(url._fields, url):  # url is a namedtuple
        if k in url_fields and v:
            new_fields[url_fields[k]] = v
    _, ext = splitext(url.path)
    if ext:
        new_fields['url.extension'] = ext.lstrip('.')
    return new_fields


def sanitize_dashes(value):
    """ Some Elastic fields format do not accept '-' as value """
    return (value if value != '-' else None)


class SuperTimeline(base.job.BaseModule):
    """ Main class to adapt any forensic source containing timestamped events to
        JSON format suitable for Elastic Common Schema (ECS)

        Configuration section:
            - **classify**: If True, categorize the files in the output.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._classifier = False

    def read_config(self):
        super().read_config()
        self.set_default_config('classify', 'True')

    def common_fields(self):
        """ Get a new dictionary of mandatory fields for all sources """
        return {'host.domain': self.myconfig('casename'),
                'host.name': self.myconfig('source'),
                'event.kind': 'event',  # one of: alert, event, metric, state, pipeline_error, signal
                'event.category': [''],  # one or more of: authentication, database, driver, file, host, intrusion_detection, malware, package, process, web
                'event.type': [''],  # one or more of: access, change, creation, deletion, end, error, info, installation, start
                'event.module': ''}

    def filegroup(self, entry, classify=True):
        """ Return the category group given an extension, path or content_type """
        if self._classifier is False:
            if classify:
                self._classifier = base.job.load_module(self.config, 'base.directory.FileClassifier')
            else:
                self._classifier = None

        if self._classifier is None:
            return ''

        return self._classifier.classify(entry)

    def run(self, path=None):
        raise NotImplementedError


class Timeline(SuperTimeline):
    """
    Convert a BODY file to events. After this, you can save this file using events.save

    Configuration section:
        - **include_filename**: if True, include FILENAME entries in the output.
        - **classify**: If True, categorize the files in the output.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('include_filename', 'False')
        self.set_default_config('classify', 'True')

    def run(self, path=None):
        """ Converts a BODY file read from from_module into an Elastic Common Schema document. """
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):
            filename = os.path.basename(d['path'])
            # do not include FILE_NAME entries if the option is on
            if (not self.myflag('include_filename')) and '$FILE_NAME' in filename:
                continue
            # Get the deleted status of the file and strip the termination
            deleted = 'false'
            if filename.endswith(' (deleted)'):
                filename = filename[: - len(' (deleted)')]
                deleted = 'true'
            elif filename.endswith(' (deleted-realloc)'):
                filename = filename[: - len(' (deleted-realloc)')]
                deleted = 'true'

            common = self.common_fields()
            common.update({
                'tags': ['fs'],
                'event.category': ['file'],
                'event.module': 'filesystem',
                'event.dataset': 'MFT',
                'file.path': d['path'],
                'file.directory': os.path.dirname(d['path']),
                'file.extension': os.path.splitext(filename)[1].lstrip('.'),
                'file.name': filename,
                'file.accessed': to_date(d['file_access']),
                'file.created': to_date(d['file_birth']),
                'file.mtime': to_date(d['file_modified']),
                'file.ctime': to_date(d['file_changerecord']),
                'file.size': d['file_size'],
                'file.inode': d['file_inode'],
                'file.uid': d['file_uid'],
                'file.gid': d['file_gid'],
                'file.mode': permissions_to_octal(d['file_mode']),
                'file.type': filetype(d['file_mode']),
                'file.group': self.filegroup(d, self.myflag('classify')) or '',
                'file.deleted': deleted
            })

            common.update({
                '@timestamp': to_date(d['file_birth']),
                'message': 'File birth: ' + d['path'],
                'event.action': 'file-birth',
                'event.type': ['creation']
            })
            yield common
            common.update({
                '@timestamp': to_date(d['file_modified']),
                'message': 'File modified: ' + d['path'],
                'event.action': 'file-modified',
                'event.type': ['change']
            })
            yield common
            common.update({
                '@timestamp': to_date(d['file_changerecord']),
                'message': 'File change record: ' + d['path'],
                'event.action': 'file-changed',
                'event.type': ['change']
            })
            yield common
            common.update({
                '@timestamp': to_date(d['file_access']),
                'message': 'File access: ' + d['path'],
                'event.action': 'file-accessed',
                'event.type': ['access']
            })
            yield common


class RecentFiles(SuperTimeline):
    """ Converts Lnk and Jumplists to events. After this, you can save this file using events.save.

    Configuration section:
        - **classify**: If True, categorize the files in the output.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('classify', 'True')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):

            common = self.common_fields()
            common.update({
                'tags': ['recentfiles'],
                'event.category': ['file'],
                'event.type': ['access'],
                'event.module': 'recentfiles',
                'event.dataset': d['artifact'],
                'recent.application': d['application'],
                'recent.last_open': to_iso_format(d['last_open_date']),
                'recent.first_open': to_iso_format(d['first_open_date']),
                'recent.network_path': d['network_path'],
                'recent.drive_type': d['drive_type'],
                'recent.drive_sn': d['drive_sn'],
                'recent.machine_id': d['machine_id'],
                'recent.file': d['file'],
                'user.name': d['user'],
                'file.path': d['path'],
                'file.size': d['size'],
                'file.directory': os.path.dirname(d['path']),
                'file.extension': os.path.splitext(d['path'])[1].lstrip('.'),
                'file.name': os.path.basename(d['path']),
                'file.group': self.filegroup(d, self.myflag('classify')) or ''
            })

            if d['artifact'] == 'lnk':
                common.update({
                    '@timestamp': to_iso_format(d['last_open_date']),
                    'message': 'File last opened: ' + d['path'],
                    'event.action': 'file-last-opened'
                })
                yield common
                common.update({
                    '@timestamp': to_iso_format(d['first_open_date']),
                    'message': 'File first opened: ' + d['path'],
                    'event.action': 'file-first-opened'
                })
                yield common

            elif d['artifact'] == 'jlauto':
                common.update({
                    '@timestamp': to_iso_format(d['last_open_date']),
                    'message': 'File last opened: ' + d['path'],
                    'event.action': 'file-last-opened'
                })
                yield common

            elif d['artifact'] == 'jlcustom':
                common.update({
                    '@timestamp': datetime.datetime.fromtimestamp(0).isoformat(),  # No timestamp. Set to LINUX epoch
                    'message': 'File last opened: ' + d['path'],
                    'event.action': 'file-last-opened'
                })
                yield common


class BrowsersHistory(SuperTimeline):
    """ Converts browsers history to events. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):

            common = self.common_fields()
            common.update({
                'tags': ['browsers'],
                'user.name': d['user'],
                'event.category': ['web'],
                'event.type': ['access'],
                'event.module': 'browsers',
                'event.dataset': 'history',
                'event.action': 'url-last-visited',
                'user_agent.name': d['browser'],
                'url.full': d['url'],
                'url.last_visit': to_iso_format(d['last_visit']),
                'message': 'Url visited: ' + d['url']
            })
            common.update(decompose_url(d['url']))

            if d['browser'] == 'chrome':
                common.update({
                    '@timestamp': to_iso_format(d['visit_date']),
                    'url.title': d['title'],
                    'url.visit_count': d['visit_count'],
                    'url.visit_type': d['visit_type'],
                    'url.visit_type_description': d['type_description'],
                    'url.visit_duration': d['visit_duration']
                })
                yield common

            elif d['browser'] == 'firefox':
                common.update({
                    '@timestamp': to_iso_format(d['last_visit']),
                    'url.title': d['title'],
                    'url.visit_count': d['visit_count'],
                    'url.visit_type': d['visit_type'],
                    'url.visit_type_description': d['type_description']
                })
                yield common

            elif d['browser'] == 'safari':
                common.update({
                    '@timestamp': to_iso_format(d['last_visit']),
                    'url.title': d['title']
                })
                yield common

            elif d['browser'] == 'edge':
                common.update({
                    '@timestamp': to_iso_format(d['last_visit']),
                    'url.modified': to_iso_format(d['modified'])
                })
                yield common

            elif d['browser'] == 'ie':
                common.update({
                    '@timestamp': to_iso_format(d['last_visit']),
                    'url.last_checked': d['last_checked']
                })
                yield common


class BrowsersCookies(SuperTimeline):
    """ Converts browsers cookies to events. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):

            common = self.common_fields()
            common.update({
                'tags': ['browsers'],
                'user.name': d['user'],
                'event.category': ['web'],
                'event.module': 'browsers',
                'event.dataset': 'cookies',
                'user_agent.name': d['browser'],
                'url.original': d['url'],
                'cookie.name': d.get('cookie_name', ''),
                'cookie.value': d.get('cookie_value', ''),
                'cookie.created': to_iso_format(d.get('creation', '1970-01-01 01:00:00'))
            })
            if 'accessed' in d:
                common.update({'cookie.accessed': to_iso_format(d.get('accessed', '1970-01-01 01:00:00'))})

            if d['browser'] in ['chrome', 'firefox']:
                common.update({
                    '@timestamp': to_iso_format(d['accessed']),
                    'event.type': ['access'],
                    'event.action': 'cookie-accessed',
                    'message': 'Cookie accessed for: ' + d['url'],
                })
                yield common
                common.update({
                    '@timestamp': to_iso_format(d['creation']),
                    'event.type': ['creation'],
                    'event.action': 'cookie-created',
                    'message': 'Cookie created for: ' + d['url'],
                })
                yield common

            elif d['browser'] == 'safari':
                common.update({
                    '@timestamp': to_iso_format(d['creation']),
                    'event.type': ['creation'],
                    'event.action': 'cookie-created',
                    'message': 'Cookie created for: ' + d['url'],
                    'cookie.expires': to_iso_format(d['expires']),
                    'cookie.path': d['path']
                })
                yield common

            elif d['browser'] == 'edge':
                common.update({
                    '@timestamp': to_iso_format(d['creation']),
                    'event.type': ['creation'],
                    'event.action': 'cookie-created',
                    'message': 'Cookie created for: ' + d['url'],
                    'cookie.expires': to_iso_format(d['expires'])
                })
                yield common
                common.update({
                    '@timestamp': to_iso_format(d['accessed']),
                    'event.type': ['access'],
                    'event.action': 'cookie-accessed',
                    'message': 'Cookie accessed for: ' + d['url'],
                })
                yield common


class BrowsersDownloads(SuperTimeline):
    """ Converts browsers downloads to events. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        pass
        # TODO: differs too much for browser type. Some without timestamps


class EventLogs(SuperTimeline):
    """ Adapts windows event logs to Elastic. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):

            common = self.common_fields()
            common.update({
                '@timestamp': to_iso_format(d['event.created']),
                'tags': ['event_logs'],
                'event.module': 'event_logs',
                'event.code': d['event.code'],
                'event.dataset': d['event.dataset'],
                'event.provider': d['event.provider']
            })

            common['message'] = d.get('description', "Event Code: {} ({})".format(d['event.code'], d['event.dataset']))
            # print(d['description'], common['message'])
            parsed_fields = set(['event.created', 'event.code', 'event.dataset', 'event.provider', 'description'])

            # Optional fields
            for field in ['event.category', 'event.type', 'event.action', 'process.pid', 'process.thread.id']:
                if field in d:
                    common[field] = d[field]
                    parsed_fields.add(field)

            # EventData and UserData only exist in parsed event_logs when are not specific event codes
            parsed_fields.update(['EventData', 'UserData'])

            # Selected data fields
            for field in [f for f in d if f not in parsed_fields]:
                if field == 'url':  # in conflict with ECS
                    field = 'url.full'
                elif field.endswith('ip') or field.endswith('port'):
                    d[field] = sanitize_dashes(d[field])
                if field.startswith('data.'):
                    common.update({'event.{}'.format(field): d[field]})
                else:
                    common.update({field: d[field]})
            yield common


class Prefetch(SuperTimeline):
    """ Converts prefetch execution times to events. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):

            common = self.common_fields()
            common.update({
                'tags': ['execution'],
                'event.category': ['package'],
                'event.module': 'prefetch',
                'event.dataset': 'prefetch',
                'event.action': 'application-executed',
                'event.type': ['start'],
                'message': "Executed process: {}".format(d['Executable']),
                'file.name': d['Filename'],
                'file.group': 'plain',
                'process.executable': d['Executable'],
                'executable.run_count': d['Run count'],
                'executable.first_run': d['Birth time']
            })
            for t in range(8):
                field = 'Run time {}'.format(t)
                if d[field]:
                    common['@timestamp'] = common['process.start'] = to_iso_format(d[field])
                    common['executable.run_time'] = t
                    yield common


class UsnJrnl(SuperTimeline):
    """ Adapts windows usnjrnl to Elastic. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        # CSV fields: Date;Filename;Full Path;File Attributes;Reason;MFT Entry;Parent MFT Entry;Reliable Path
        for d in self.from_module.run(path):

            common = self.common_fields()
            common.update({
                '@timestamp': to_iso_format(d['Date']),
                'tags': ['journal'],
                'event.category': ['package'],
                'event.module': 'usnjrnl',
                'event.dataset': 'usnjrnl',
                'file.path': d['Full Path'],
                'file.name': d['Filename'],
                'file.directory': os.path.dirname(d['Full Path']),
                'file.inode': d['MFT Entry'],
                'file.group': self.filegroup(dict({'path': d['Full Path']}), self.myflag('classify')) or '',
                'file.attributes': self.attributes(d['File Attributes']),
                'event.action': self.reasons(d['Reason'])
            })

            deleted = common['event.action'] == 'file-deleted'
            common['file.deleted'] = deleted
            event_types_messages = {'file-created': (['creation'], "File created"),
                                    'file-deleted': (['deletion'], 'File deleted'),
                                    'file-renamed-old-name': (['change'], 'File renamed. Old name'),
                                    'file-renamed-new-name': (['change'], 'File renamed. New name')}
            common['event.type'] = event_types_messages.get(common['event.action'], [''])[0]
            # print(event_types_messages.get(common['event.action'], ['', ''])[1])
            common['message'] = "{}: {}".format(event_types_messages.get(common['event.action'], ['', ''])[1], d['Full Path'])

            yield common

    def attributes(self, attributes):
        """ Converts a string of attributes into a list:

        Example:
        'ARCHIVE NOT_CONTENT_INDEXED ' -> ["archive", "not_content_indexed"]
        """

        attr = attributes.split(' ')
        return [a.lower() for a in attr[:-1]]

    def reasons(self, reasons):
        """ Parse a string of reasons into a suitable event.action:

        Example:
        'DATA_EXTEND FILE_CREATE CLOSE ' -> 'file-created'
        """

        outcome = {'FILE_CREATE': 'file-created',
                   'FILE_DELETE': 'file-deleted',
                   'RENAME_OLD_NAME': 'file-renamed-old-name',
                   'RENAME_NEW_NAME': 'file-renamed-new-name'}
        actions = [s for s in reasons.split(' ')[:-1]]
        for a in actions:
            if a in outcome:
                return outcome[a]
        return []


class USB(SuperTimeline):
    """ Adapts usb setup.api to Elastic. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):
            common = self.common_fields()
            common.update({
                'tags': ['usb'],
                'event.category': ['driver'],
                'event.module': 'usb',
                'event.dataset': 'setupapi',
                'package.name': d['Device'],
                'package.description': d['DevDesc']
            })

            common.update({
                '@timestamp': to_iso_format(d['Start']),
                'event.type': ['installation', 'start'],
                'event.action': 'driver-installation-started',
                'message': 'Driver installation start: {}'.format(d['Device'])
            })
            yield common

            common.update({
                '@timestamp': to_iso_format(d['End']),
                'package.installed': to_iso_format(d['End']),
                'event.action': 'driver-installation-ended',
                'message': 'Driver installation end: {}'.format(d['Device']),
                'event.type': ['installation', 'end']
            })
            yield common


class NetworkUsage(SuperTimeline):
    """ Adapts SRUM Network Usage information to Elastic. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):
            common = self.common_fields()
            common.update({
                '@timestamp': to_iso_format(d['SRUM ENTRY CREATION']),
                'event.kind': "metric",
                'tags': ['network'],
                'event.category': ['web'],
                'event.module': 'srum',
                'event.dataset': 'network-usage',
                'event.action': 'network-usage-summary',
                'event.type': ['info'],
                'network.application': d['Application'],
                'network.name': d['Profile'],
                'network.type': d['Interface'],
                'source.bytes': d['Bytes Sent'],
                'destination.bytes': d['Bytes Received'],
                'message': "Application {} uploaded/downloaded {} / {} bytes in last summary period".format(
                    d['Application'], d['Bytes Sent'], d['Bytes Received'])
            })

            user = d.get('User SID', '').split(' ')
            common['user.id']: user[0]
            if len(user) > 1:
                common['user.name'] = ' '.join(user[1:]).lstrip('(').rstrip(')')

            yield common


class NetworkConnections(SuperTimeline):
    """ Adapts SRUM Network Connections information to Elastic. After this, you can save this file using events.save.
    """

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):
            common = self.common_fields()
            common.update({
                '@timestamp': to_iso_format(d['ConnectStartTime']),
                'tags': ['network'],
                'event.category': ['web'],
                'event.module': 'srum',
                'event.dataset': 'network-connections',
                'event.action': 'connection-started',
                'event.type': ['start'],
                'network.application': d['Application'],
                'network.name': d['L2ProfileId'],
                'network.type': d['InterfaceLuid'],
                'network.time_connected': d['ConnectedTime'],  # in seconds
                'message': 'Started a {} network connection{}'.format(
                    d['InterfaceLuid'], ' on {}'.format(d['L2ProfileId']) if d['L2ProfileId'] else '')
            })

            user = d.get('User SID', '').split(' ')
            if user[0]:
                common['user.id']: user[0]
            if len(user) > 1:
                common['user.name'] = ' '.join(user[1:]).lstrip('(').rstrip(')')

            yield common


class Registry(SuperTimeline):
    """ Adapts Windows Registry information to Elastic. After this, you can save this file using events.save. """

    def run(self, path=""):
        self.check_params(path, check_from_module=True)

        for d in self.from_module.run(path):
            if 'values' not in d:  # No value set, just subkey description
                continue

            common = self.common_fields()
            common.update({
                '@timestamp': d['timestamp'],
                'tags': ['registry'],
                'event.category': ['database'],
                'event.module': 'registry',
                'event.dataset': d['hive_name'],
                'event.action': 'registry value-set',
                'event.type': ['change'],  # could be also creation
                'registry.path': d['path'],
                'registry.key': d['subkey']
            })

            if d.get('user', ''):
                common['user.name'] = d['user']

            for v in d['values']:
                for sub_value, data in v.items():
                    common['registry.{}'.format(sub_value)] = data
                common['message'] = 'Registry value {} set at subkey {}'.format(v['value'], d['subkey'])
                yield common
