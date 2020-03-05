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
import leveldb
import tempfile
import shutil
import datetime
import struct
import dateutil.parser

from base.utils import save_csv, save_json
import base.job


class Skype(base.job.BaseModule):
    """ Parse Skype databases leveldb """
    def run(self, path=''):
        if (not path.endswith('leveldb')) and (not path.endswith('main.db')):
            raise base.job.RVTError('Expected a db file or leveldb folder. Path: {}'.format(path))
        temp_dir = tempfile.mkdtemp('skype')
        temp_path = os.path.join(temp_dir, 'Default')
        try:
            shutil.copytree(path, temp_path)
            self.user = self.config.config['skype.parameters']['user']
            self.partition = self.config.config['skype.parameters']['partition']
            self.out_folder = self.myconfig('voutdir') if self.myflag('vss') else self.myconfig('outdir')
            ParseSkypeLevelDB(temp_path, outdir=self.out_folder, user=self.user, partition=self.partition).run()
        finally:
            shutil.rmtree(temp_dir)
        return []


class Teams(base.job.BaseModule):
    """ Parse Teams databases leveldb """
    def run(self, path=''):
        if not path.endswith('leveldb') or not path.endswith('main.db'):
            raise base.job.RVTError('Expected a db file or leveldb folder. Path: {}'.format(path))
        temp_dir = tempfile.mkdtemp('teams')
        temp_path = os.path.join(temp_dir, 'Default')
        try:
            shutil.copytree(path, temp_path)
            self.user = self.config.config['teams.parameters']['user']
            self.partition = self.config.config['teams.parameters']['partition']
            self.out_folder = self.myconfig('voutdir') if self.myflag('vss') else self.myconfig('outdir')
            ParseTeamsLevelDB(temp_path, outdir=self.out_folder, user=self.user, partition=self.partition).run()
        finally:
            shutil.rmtree(temp_dir)
        return []


class GenericLevelDB(base.job.BaseModule):
    """ Parse any leveldb. Since it is general, all specific fields are not parsed """
    def run(self, path=''):
        if not os.path.isdir(path):
            raise base.job.RVTError('Expected a directory as path. {}'.format(path))
        temp_dir = tempfile.mkdtemp('leveldb')
        temp_path = os.path.join(temp_dir, 'Default')
        try:
            shutil.copytree(path, temp_path)
            import subprocess
            subprocess.call(['chmod', '-R', '655', temp_path])
            self.user = self.config.config['generic.parameters']['user']
            self.partition = self.config.config['generic.parameters']['partition']
            self.out_folder = self.myconfig('voutdir') if self.myflag('vss') else self.myconfig('outdir')
            ParseLevelDB(temp_path, outdir=self.out_folder, user=self.user, partition=self.partition).run()
        finally:
            shutil.rmtree(temp_dir)
        return []


class ParseLevelDB():
    """ Base class for parsing leveldb. Methods 'get_types_table', 'get_target_type' and 'filter_special_keys' must be implemented """

    def __init__(self, path=None, outdir=None, user='', partition='', prefix=''):
        if path is None:
            raise Exception('Please, enter a leveldb folder path')
        self.path = path
        self.outdir = outdir if outdir else os.getcwd()
        self.prefix = prefix
        self.user = user
        self.partition = partition

        self.get_types_table()
        for typ in self.table:
            # self.table[typ]['out_file'] = '{}{}.csv'.format(self.user + '_' if self.user else '', typ)
            self.table[typ]['out_file'] = '{}.csv'.format(typ)
            self.table[typ]['data'] = []

    def run(self):
        """ Main function to execute """
        # Write dump file
        dump_file = os.path.join(self.outdir, 'dump.json')
        if os.path.exists(dump_file):
            os.remove(dump_file)
        for entry in self.get_leveldb_pairs(self.path):
            save_json(self.parse_db(entry), outfile=dump_file)

        self.write_tables()

    def get_types_table(self):
        """ Creates the table relating types of entries with fields

        Example:
        self.table = {
            'messages': {'identifier': 'originalarrivaltime',
                         'fields': ['originalarrivaltime', 'creator', 'conversationId', 'content'],
                         'sort': 'originalarrivaltime'},
            'calls': {'identifier': 'callDirection',
                      'fields': ['startTime', 'connectTime', 'endTime', 'callDuration', 'originator', 'target'],
                      'sort': None},
        """

        self.table = {}

    def get_leveldb_pairs(self, lvl_db_path):
        """ Generator of key-value pairs for all leveldb files inside a folder."""
        # Load db. Some leveldb use 'idb_cmp1' to sort results
        prefix = self.prefix
        try:
            db = leveldb.LevelDB(lvl_db_path, create_if_missing=False)
        except Exception:
            try:
                db = leveldb.LevelDB(lvl_db_path, create_if_missing=False, comparator=('idb_cmp1', comparator))
            except Exception as e:
                raise(e)

        # Get pairs
        for pair in db.RangeIter():
            if not isinstance(pair, tuple) or len(pair) != 2:  # Not a (key, value) valid tuple
                continue
            if str(pair[0]).startswith(prefix):  # Omit prefix in keys and yield {key: value} dict
                key, value = pair
                key = key[len(prefix):]
                yield {"key": key, "value": value}

    def parse_db(self, entry):
        """ Main function for parsing leveldb """
        is_key = True  # store current field state (key or value)
        k, v = '', ''
        out = {}

        if entry['value'].find(b'"') == -1:
            if len(entry['value']) and entry['value'][0] == 0:
                entry['value'] = entry['value'].replace(b'\x00', b'')
            yield {'key': self.decode_value(entry['key']), 'value': self.decode_value(entry['value'])}

        else:  # Values are a series of key-value pairs separated by "
            for i, field in enumerate(entry['value'].split(b'"')):
                if i == 0:  # skip first field
                    continue
                le = len(field)
                if not le:  # empty field
                    continue
                if le == 1:  # skip field
                    is_key = not is_key
                    continue

                elif (le - 1) > field[0]:  # composed field
                    if is_key:  # first part is the key and the rest is the value
                        k = self.decode_value(field[1:field[0] + 1])
                        v = self.filter_special_keys(k, field[field[0] + 1:])
                        out[k] = v
                    else:  # keep only the first part as value. Unknown ending
                        v = self.filter_special_keys(k, field[1:field[0] + 1])
                        out[k] = v
                        is_key = not is_key  # change state
                    continue

                if is_key:
                    k = self.decode_value(field[1:])
                else:
                    v = field[1:]
                    out[k] = self.decode_value(v)
                is_key = not is_key

            # Process message, calls, docs
            for t in self.table.keys():
                self.get_target_type(out, t)
            yield {'key': self.decode_value(entry['key']), 'value': out}

    def write_tables(self):
        """ Write csv files containing information for each of defined tables. """
        for typ in self.table:
            values = self.table[typ]['data']
            if self.table.get('sort'):
                values = sorted(self.table[typ]['data'], key=lambda x: x[self.table[typ]['sort']])

            # Generator to update with user and partition and yield to save to csv
            def update_gen(elements):
                for element in elements:
                    element.update({'partition': self.partition, 'user': self.user})
                    yield element
            save_csv(update_gen(values), outfile=os.path.join(self.outdir, self.table[typ]['out_file']), file_exists='APPEND')

    def get_target_type(self, out, tipe):
        """ Append data to table when out contains the required identifier. """
        raise NotImplementedError

    def filter_special_keys(self, k, v):
        """ Some keys may be parsed or decoded in a special way. """
        return v
        # raise NotImplementedError

    @staticmethod
    def decode_value(b):
        """ Try to decode a bytearray """
        try:
            value = b.replace(b'\x00', b'').decode()
        except UnicodeDecodeError:
            try:
                value = b.decode('utf-16')
            except Exception:
                value = str(b)
        return value


class ParseSkypeLevelDB(ParseLevelDB):

    def get_types_table(self):
        self.table = {
            'messages': {'identifier': 'originalarrivaltime',
                         'fields': ['originalarrivaltime', 'creator', 'conversationId', 'content'],
                         'sort': 'originalarrivaltime'},
            'calls': {'identifier': 'callDirection',
                      'fields': ['startTime', 'connectTime', 'endTime', 'callDuration', 'originator', 'target'],
                      'sort': None},
            'docs': {'identifier': 'localFileName',
                     'fields': ['lastUpdatedTimestamp', 'localUri', 'localFileName', 'sizeInBytes'],
                     'sort': 'lastUpdatedTimestamp'},
            'inputs': {'identifier': 'inputEntities',
                       'fields': ["timestamp", "conversationId", "inputEntities"],
                       'sort': 'timestamp'}
        }

    def get_target_type(self, out, typ):
        message = {}
        if self.table[typ]['identifier'] in out:
            duration, connect_time, end_time = 0, 0, 0
            for t in self.table[typ]['fields']:
                try:
                    if t == 'connectTime':
                        connect_time = dateutil.parser.parse(out.get(t, ''))
                    elif t == 'endTime':
                        end_time = dateutil.parser.parse(out.get(t, ''))
                    else:
                        message[t] = out.get(t, '')
                except Exception:
                    continue
                if connect_time and end_time and not message.get('callDuration', ''):
                    duration = end_time - connect_time
                    message['callDuration'] = int(duration.total_seconds())

            self.table[typ]['data'].append(message)

    def filter_special_keys(self, k, v):
        if k in ['createdTime', 'lastUpdatedTimestamp', 'composeTime',
                 'time', '_timestamp', 'lastCallTime', 'messageHistoryStartTime',
                 'consumptionHorizonTimestamp', 'expiration', 'lastUpdate',
                 'fetchedDate', 'timestamp']:
            try:
                timestamp = struct.unpack('<d', v[1:9])[0]
                # Timestamp is in miliseconds and must be divided by 1000.
                v = datetime.datetime.utcfromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
                return v
            except Exception:
                return self.decode_value(v)
        elif k in ['sizeInBytes']:
            return self.decode_value(v)  # TODO:get size
        elif k == 'content':
            if v.find(b'U\x00R\x00I') != -1:
                pass  # TODO: make something to get uri
            return self.decode_value(v)
        elif k == 'participants':
            pass  # TODO: make something to obtain all partitcipants
            return self.decode_value(v)

        return self.decode_value(v)


class ParseTeamsLevelDB(ParseLevelDB):

    def get_types_table(self):
        self.table = {
            'messages': {'identifier': 'originalarrivaltime', 'messagetype': 'RichText/Html',
                         'fields': ['originalarrivaltime', 'displayName', 'trimmedMessageContent'],
                         'sort': 'originalarrivaltime'},
            'calls': {'identifier': 'originalarrivaltime', 'messagetype': 'Event/Call',
                      'fields': ['originalarrivaltime', 'clientArrivalTime', 'displayName', 'trimmedMessageContent'],
                      'sort': None}
        }

    def get_target_type(self, out, typ):
        message = {}
        if self.table[typ]['identifier'] in out:
            if self.table[typ]['identifier'] == 'originalarrivaltime':
                if not self.table[typ]['messagetype'] == out["messagetype"]:
                    return

            for t in self.table[typ]['fields']:
                message[t] = out.get(t, '')
            self.table[typ]['data'].append(message)

    def filter_special_keys(self, k, v):
        if k in ['createdTime', 'lastUpdatedTimestamp', 'composeTime',
                 'time', '_timestamp', 'lastCallTime', 'messageHistoryStartTime',
                 'consumptionHorizonTimestamp', 'expiration', 'lastUpdate',
                 'fetchedDate', 'timestamp', 'replyChainLatestDeliveryTime']:
            try:
                timestamp = struct.unpack('<d', v[1:9])[0]
                # Timestamp is in miliseconds and must be divided by 1000.
                v = datetime.datetime.utcfromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
                return v
            except Exception:
                return self.decode_value(v)
        elif k in ['sizeInBytes']:
            return self.decode_value(v)  # TODO:get size

        return self.decode_value(v)


def comparator(a, b):
    """ Dummy string comparator for sorting leveldb keys in case the standard leveldb.BytewiseComparator is not allowed. """
    a, b = a.lower(), b.lower()
    if a < b:
        return -1
    if a > b:
        return 1
    return 0
