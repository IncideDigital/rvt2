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
import sqlite3
import shutil
import hashlib
import base64
import dateutil.parser
from collections import OrderedDict
from contextlib import closing

import base.utils


def get_contacts(wa_db):
    """ Associate phone numbers to names and groups to ids """
    query = "SELECT jid, display_name FROM wa_contacts"
    contacts = {}
    with sqlite3.connect('file://{}?mode=ro'.format(wa_db), uri=True) as conn:
        with closing(conn.cursor()) as cursor:
            for line in cursor.execute(query):
                if line[1] is not None:
                    contacts[line[0]] = line[1]
    return contacts


class WhatsAppAndroid(base.job.BaseModule):
    """
    Parse the WhatsApp Android database.

    Configuration section:
        media_outdir: Save media to this directory. It is a python format string, with a parameter message_group
        message_group: If set, output only messages in this message group
        start_date: If set, output only messages from this date
        end_date: If set, output only messages until this date
    """

    type_switcher = {
        0: "Text message",
        1: "Image",
        2: "Audio",
        3: "Video",
        4: "Contact",
        5: "Location",
        13: "Video",  # mp4
        7: "Url",  # Not confirmed
        8: "Document",  # Not confirmed
        10: "Key change",   # Not confirmed
        11: "Video",  # Not confirmed
        14: "Deleted",   # Not confirmed
        15: "Image"  # Not confirmed
    }

    status_switcher = {
        0: "received",
        4: "waiting",  # waiting on the central server
        5: "received at destination",
        6: "control message",
        13: "read"  # message opened by the recipient
    }

    def read_config(self):
        super().read_config()
        self.set_default_config('message_group', '')
        self.set_default_config('media_outdir', os.path.join(self.config.get('ios.common', 'iosdir'), 'whatsapp', self.myconfig('message_group')))
        self.set_default_config('start_date', '')
        self.set_default_config('end_date', '')

    def run(self, path):
        """
        Parameters:
            path (str): Path to an unbacked backup
        """
        # Check existance of backup and database
        self.check_params(path, check_path=True, check_path_exists=True)
        self.backup_dir = path
        self.hashes = None

        db_file = os.path.join(os.path.join(path, 'data/com.whatsapp/databases/msgstore.db'))
        if not base.utils.check_file(db_file):
            self.logger().warning("The file %s do not exists", db_file)
            return []

        contacts_db = os.path.join(os.path.join(path, 'data/com.whatsapp/databases/wa.db'))
        self.contacts = get_contacts(contacts_db)

        self.message_group = self.myconfig('message_group', '')
        self.media_outdir = self.myconfig('media_outdir').format(message_group=self.message_group)
        base.utils.check_folder(self.media_outdir)

        # Execute query and parse messages
        self.logger().debug('Parsing: %s', db_file)
        with sqlite3.connect('file://{}?mode=ro'.format(db_file), uri=True) as conn:
            with closing(conn.cursor()) as cursor:
                cursor = self.execute_query(db_file, cursor)
                for line in cursor:
                    for message in self.parse_query(line):
                        yield message

        return []

    def execute_query(self, chatstorage_file, cursor):
        """ Creates a custom view and executes a query based on the parameters:
                - message_group
                - start_date
                - end_date

            Returns a cursor object
        """

        # Create custom view from tables ZWAMESSAGE, ZWAMESSAGEINFO, ZWACHATSESSION and ZWAMEDIAITEM
        view_query = ''' CREATE TEMPORARY VIEW composite AS
                        SELECT
                            messages.key_id,
                            messages.key_from_me,
                            messages.key_remote_jid,
                            messages.remote_resource AS group_sender,
                            messages.data AS message,
                            DATETIME(messages.timestamp / 1000, 'unixepoch') AS date_sent,
                            DATETIME(messages.received_timestamp / 1000, 'unixepoch') AS date_delivered,
                            messages.media_wa_type AS message_type,
                            messages.media_mime_type,
                            messages.status,
                            messages.media_size,
                            messages.media_name,
                            messages.media_hash,
                            messages.latitude,
                            messages.longitude,
                            message_thumbnails.thumbnail
                            FROM messages
                            LEFT JOIN message_thumbnails ON messages.key_id = message_thumbnails.key_id
                            WHERE messages.received_timestamp != "-1"
                '''

        # Filter by dates and group
        query = "SELECT * FROM composite"
        query = self.filter_query(query)
        query += ' ORDER BY date_sent'

        # Execute queries
        cursor.execute("drop view if exists composite;")
        cursor.execute(view_query)
        cursor.execute(query)
        return cursor

    def filter_query(self, query):
        """ Filter by dates and group """
        # Dates filter
        dates = {'start_date': '', 'end_date': ''}
        for limit_date in dates:
            if self.myconfig(limit_date):
                try:
                    dates[limit_date] = dateutil.parser.parse(self.myconfig(limit_date)).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    raise base.job.RVTError('Parameter start_date {} not recognized as correct date. Try something like 2019-08-25'.format(self.myconfig(limit_date)))
        start_date_filter = 'date_sent > "{}"'.format(dates['start_date']) if dates['start_date'] else ''
        end_date_filter = 'date_sent < "{}"'.format(dates['end_date']) if dates['end_date'] else ''

        # Message group filter
        group_filter = 'key_remote_jid == "{}"'.format(self.message_group) if self.message_group else ''

        # Global filtered query
        activated_filters = list(filter(None, [group_filter, start_date_filter, end_date_filter]))
        num_filters = len(activated_filters)
        if num_filters >= 1:
            query += ' WHERE {}'.format(activated_filters[0])
        if num_filters >= 2:
            query += ' AND {}'.format(activated_filters[1])
        if num_filters == 3:
            query += ' AND {}'.format(activated_filters[2])

        return query

    def parse_query(self, line):
        """ Parse the query and yields a dictionary """
        # line index reference:
        # 0:id, 1:is_from_me, 2:remote_jid, 3:group_sender, 4:text(message)
        # 5:timestamp, 6:date_sent, 7:message_type, 8: mime_type
        # 9:status, 10:media_size, 11:media_name, 12:media_hash
        # 13: latitude, 14: longitude, 15:thumbnail

        # Origin and destination
        # In individual chats: remote_jid = {phone number}@whatsapp.net
        # In group chats: remote_jid = {creator’s phone number}-{creation time}@g.us
        from_me = line[1] == 1
        phone, ext = line[2].split('@')
        group_id = line[2]

        if ext == 'whatsapp.net':
            dest = self.contacts.get(line[2], phone)
            origin, destination = ('ME', dest) if from_me else (dest, 'ME')
        elif ext == 'g.us':
            creator = phone.split('-')[0]   # TODO: convert creator into group_id
            group_name = self.contacts.get(line[2], creator)
            origin, destination = ('ME', group_name) if from_me else (self.contacts.get(line[3], line[3].split('@')[0]), 'ME')
            phone = line[3].split('@')[0] if line[3] else ''
        else:
            origin, destination = ('ME', group_id) if from_me else (group_id, 'ME')

        # Dates
        date_sent = line[5] if from_me else ''
        date_received = line[6] if not from_me else ''
        date_recorded = line[6] if from_me else line[5]

        # Phone_number
        # phone_number = "" if line[4] is None else line[4].split("@")[0]

        # Message and status types
        readable_type = self.type_switcher.get(int(line[7]), "Unknown: {}".format(line[7]))
        mime_type = line[8] if line[8] else ''
        status = self.status_switcher.get(line[9], line[9])

        # Message for the several types
        # message = "[System message: {}]".format(readable_type)
        if line[4] is not None:
            if readable_type != "Contact":
                message = line[4].replace("\n", " ")
            else:
                message = "[Contact]: {}".format(line[11])
        else:
            message = ''

        # Basename of media file related to message
        media_filename = self.get_media_filename(media_hash=line[12],
                                                 message_type=int(line[7]),
                                                 media_name=line[11],
                                                 message_group=group_id,
                                                 key_id=line[0],
                                                 media_thumbnail=line[15])

        # Location coordinates. Only make sense for the next message types: 5, 1, 2
        lon_lat = ''
        if line[13] and line[14]:
            lon_lat = ', '.join([str(line[14]), str(line[13])])

        yield OrderedDict(
            message_id=line[0],
            message_from=origin,
            message_to=destination,
            message_phonenumber=phone,
            date_creation=date_recorded,
            date_sent=date_sent,
            date_delivered=date_received,
            message=message,
            message_type=readable_type,
            status=status,
            message_media_location=media_filename,
            message_group=group_id,
            lon_lat=lon_lat,
            mime_type=mime_type
        )

    def get_media_filename(self, media_hash, message_type, media_name, message_group, key_id, media_thumbnail=None):
        """ Get basename of media file related to message """

        media_outdir = self.media_outdir
        hashes = self._get_hashes()

        if message_type not in [1, 2, 3, 13]:  # Only certain type of messages contain media
            return ''

        if media_hash is None or media_hash not in hashes:
            media_filename = self._get_thumbnail(thumbnail=media_thumbnail, key_id=key_id, outdir=media_outdir)
            if media_filename:
                return media_filename
            else:  # Warn for media files not found when expected
                return '[System message: {}]: not found'.format(self.type_switcher[message_type])

        media_location = media_name if media_name else hashes[media_hash]
        media_filename = os.path.basename(media_location)
        # Copy media files in order to reference them in the same directory only by its basename
        shutil.copy2(os.path.join(media_location), os.path.join(media_outdir, media_filename))
        return media_filename

    def _get_thumbnail(self, thumbnail, key_id, outdir):
        """ Convert binary data to proper format and write it to media_outdir with basename 'key_id' """
        if thumbnail is None:
            return ''
        thumbnail_basename = key_id + ".jpg"
        thumbnail_path = os.path.join(outdir, thumbnail_basename)
        with open(thumbnail_path, 'wb') as file:
            file.write(thumbnail)
        return thumbnail_basename

    def _get_hashes(self):
        if self.hashes is not None:
            return self.hashes

        self.hashes = {}
        # Media directory. Depends on Whatsapp version
        mediafolders = [os.path.join(self.backup_dir, "data/media/0/WhatsApp/Media")]
        for mediafolder in mediafolders:
            for folder, subfolder, files in os.walk(mediafolder):
                for file in files:
                    with open(os.path.join(mediafolder, folder, file), 'rb') as media_file:
                        content = media_file.read()
                        file_hash = base64.b64encode(hashlib.sha256(content).digest()).decode()
                        self.hashes[file_hash] = os.path.join(mediafolder, folder, file)

        return self.hashes


class WhatsAppChatSessionsAndroid(base.job.BaseModule):
    """ Returns all the available chat identifiers in a whatsapp database.

    The returned dictionary have a field mesage_group.
    """

    def run(self, path=None):
        self.check_params(path, check_path=True, check_path_exists=True)
        msgdb_file = os.path.join(os.path.join(path, 'data/com.whatsapp/databases/msgstore.db'))
        if not base.utils.check_file(msgdb_file):
            self.logger().warning("The file %s do not exists", msgdb_file)
            return []

        # contacts = get_contacts(os.path.join(os.path.join(path, 'data/com.whatsapp/databases/wa.db')))
        conn = sqlite3.connect('file://{}?mode=ro'.format(msgdb_file), uri=True)
        c = conn.cursor()
        for line in c.execute('SELECT DISTINCT key_remote_jid FROM messages WHERE received_timestamp != "-1"'):
            yield(dict(message_group=line[0]))
        return []
