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
import datetime
import biplist
import shutil
import dateutil.parser
from collections import OrderedDict
from contextlib import closing

import plugins.ios
import base.utils

# TODO: change reference to 'ME' by the actual whatsapp owner name


class WhatsApp(plugins.ios.IOSModule):
    """
    Parse the WhatsApp iOS database.

    Configuration section:
        media_outdir: Save media to this directory. It is a python format string, with a parameter message_group
        message_group: If set, output only messages in this message group
        start_date: If set, output only messages from this date
        end_date: If set, output only messages until this date
    """

    type_switcher = {
        0: "Text message",
        1: "Image",
        2: "Video",
        3: "Voice/Audio note",
        4: "Contact",
        5: "Location",
        7: "Url",
        8: "Document",
        10: "Key change",
        11: "Video",  # mp4
        14: "Deleted",
        15: "Image"  # webp
    }

    status_switcher = {
        0: "system",
        1: "sent",  # sent but not received by other party
        6: "delivered",  # sent and received by other party, but not read
        7: "deleted",
        8: "seen",
    }

    def read_config(self):
        super().read_config()
        self.set_default_config('media_outdir', os.path.join(self.config.get('ios.common', 'iosdir'), 'whatsapp', '{{message_group}}'))
        self.set_default_config('message_group', '')
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
        chatstorage_file = os.path.join(os.path.join(path, 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite'))
        if not base.utils.check_file(chatstorage_file):
            self.logger().warning("The file %s do not exists", chatstorage_file)
            return []

        # Execute query and parse messages
        self.logger().debug('Parsing: %s', chatstorage_file)
        with sqlite3.connect('file://{}?mode=ro'.format(chatstorage_file), uri=True) as conn:
            with closing(conn.cursor()) as cursor:
                cursor = self.execute_query(chatstorage_file, cursor)
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
        view_query = '''CREATE TEMPORARY VIEW messages AS
                            SELECT
                                ZWAMESSAGE.Z_PK,
                                ZISFROMME,
                                ZWACHATSESSION.ZPARTNERNAME,
                                ZWAMESSAGE.ZPUSHNAME,
                                ZWAMESSAGE.ZTOJID,
                                ZWAMESSAGE.ZCHATSESSION,
                                DATETIME(ZMESSAGEDATE + 978307200, 'unixepoch') AS ZMESSAGEDATE,
                                DATETIME(ZSENTDATE + 978307200, 'unixepoch') AS ZSENTDATE,
                                ZWAMESSAGE.ZTEXT,
                                ZWAMESSAGEINFO.ZRECEIPTINFO,
                                ZWAMESSAGE.ZMESSAGETYPE,
                                ZWAMESSAGE.ZMESSAGESTATUS,
                                ZWAMESSAGE.ZSPOTLIGHTSTATUS,
                                ZWAMEDIAITEM.ZMEDIALOCALPATH,
                                ZWAMEDIAITEM.ZVCARDNAME,
                                ZWAMEDIAITEM.ZLATITUDE,
                                ZWAMEDIAITEM.ZLONGITUDE
                            FROM ZWAMESSAGE
                            INNER JOIN ZWAMESSAGEINFO ON ZWAMESSAGEINFO.ZMESSAGE = ZWAMESSAGE.Z_PK
                            INNER JOIN ZWACHATSESSION ON ZWACHATSESSION.Z_PK = ZWAMESSAGE.ZCHATSESSION
                            LEFT JOIN ZWAMEDIAITEM ON ZWAMESSAGE.Z_PK = ZWAMEDIAITEM.ZMESSAGE

                            UNION ALL
                            SELECT
                                ZWAMESSAGE.Z_PK,
                                ZISFROMME,
                                ZWACHATSESSION.ZPARTNERNAME,
                                ZWAMESSAGE.ZPUSHNAME,
                                ZWAMESSAGE.ZTOJID,
                                ZWAMESSAGE.ZCHATSESSION,
                                DATETIME(ZMESSAGEDATE + 978307200, 'unixepoch') AS ZMESSAGEDATE,
                                DATETIME(ZSENTDATE + 978307200, 'unixepoch') AS ZSENTDATE,
                                ZTEXT,
                                NULL,
                                ZMESSAGETYPE,
                                ZMESSAGESTATUS,
                                ZWAMESSAGE.ZSPOTLIGHTSTATUS,
                                ZWAMEDIAITEM.ZMEDIALOCALPATH,
                                ZWAMEDIAITEM.ZVCARDNAME,
                                ZWAMEDIAITEM.ZLATITUDE,
                                ZWAMEDIAITEM.ZLONGITUDE
                            FROM ZWAMESSAGE
                            INNER JOIN ZWACHATSESSION ON ZWACHATSESSION.Z_PK = ZWAMESSAGE.ZCHATSESSION
                            LEFT JOIN ZWAMEDIAITEM ON ZWAMESSAGE.Z_PK = ZWAMEDIAITEM.ZMESSAGE
                            WHERE ZWAMESSAGE.ZMESSAGEINFO IS NULL
                            ORDER BY ZMESSAGEDATE;'''

        # Filter by dates and group
        query = 'SELECT * FROM messages'
        query = self.filter_query(query)

        # Execute queries
        cursor.execute("drop view if exists messages;")
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
        start_date_filter = 'ZMESSAGEDATE > "{}"'.format(dates['start_date']) if dates['start_date'] else ''
        end_date_filter = 'ZMESSAGEDATE < "{}"'.format(dates['end_date']) if dates['end_date'] else ''

        # Message group filter
        group_filter = 'ZCHATSESSION == {}'.format(self.myconfig('message_group')) if self.myconfig('message_group') else ''

        # Global filtered query
        activated_filters = list(filter(None, [group_filter, start_date_filter, end_date_filter]))
        num_filters = len(activated_filters)
        query = 'SELECT * FROM messages'  # messages
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
        # 0: Pk, 1: isfrome, 2:partnername, 3:pushname, 4:tojid, 5:chatsession(group)
        # 6: date_creation, 7:date_sent, 8:text(message), 9: receiptinfo, 10: message_type
        # 11: status, 12: spotlight_status, 13: media_location, 14: contact_name
        # 15: latitude, 16: longitude

        # Origin and destination
        origin, destination = ('ME', line[2]) if line[1] == 1 else (line[2], 'ME')

        # Read and delivered dates
        blob = line[9]
        if line[1] == 1 and (line[4].split("@")[1] != "broadcast") and (blob is not None) and (blob[:6] == b'bplist'):
            plist = biplist.readPlistFromString(blob)
            try:
                delivered = datetime.datetime.fromtimestamp(plist['$objects'][6]['NS.time'] + 978307200)
            except Exception:
                delivered = "-"
            try:
                read = datetime.datetime.fromtimestamp(plist['$objects'][8]['NS.time'] + 978307200)
            except Exception:
                read = 0
        else:
            delivered = 0
            read = 0

        # Phone_number
        phone_number = "" if line[4] is None else line[4].split("@")[0]

        # Message and status types
        readable_type = self.type_switcher.get(line[10], "Unknown: {}".format(line[10]))
        status = self.status_switcher.get(line[11], line[11])

        # Message for the several types
        message = "[System message: {}]".format(readable_type)
        if line[8] is not None:
            message = line[8].replace("\n", " ")

        # Basename of media file related to message
        media_filename = self.get_media_filename(media_location=line[13], message_type=line[10], message_group=line[5])

        # Location coordinates. Only make sense for the next message types: 5, 1, 2
        lon_lat = ''
        if line[15] and line[16]:
            lon_lat = ', '.join([str(line[16]), str(line[15])])

        # Contact name. Only make sense for message types: 4, 5
        contact_name = line[14] if line[14] else ''

        yield OrderedDict(
            message_id=line[0],
            message_from=origin,
            message_to=destination,
            message_phonenumber=phone_number,
            date_creation=line[6],
            date_sent=line[7],
            date_delivered=delivered,
            date_read=read,
            message=message,
            message_type=readable_type,
            status=status,
            message_media_location=media_filename,
            message_group=line[5],
            lon_lat=lon_lat,
            contact=contact_name
        )

    def get_media_filename(self, media_location, message_type, message_group):
        """ Get basename of media file related to message """

        # Media directory. Depends on Whatsapp version
        mediafolders = [os.path.join(self.backup_dir, "AppDomain-net.whatsapp.WhatsApp/Library"),
                        os.path.join(self.backup_dir, "AppDomainGroup-group.net.whatsapp.WhatsApp.shared/Message")]
        media_filename = ''

        # Warn for media files not found when expected
        if message_type in [1, 2, 3, 8, 11] and media_location is None:
            media_filename = '[System message: {}]: not found'.format(self.type_switcher[message_type])

        if media_location is not None:
            for mediafolder in mediafolders:
                if base.utils.check_file(os.path.join(mediafolder, media_location)):
                    media_location = os.path.join(self.backup_dir, mediafolder, media_location)
                    media_outdir = self.myconfig('media_outdir').format(message_group=message_group)
                    base.utils.check_folder(media_outdir)
                    media_filename = os.path.basename(media_location)
                    # Copy media files in order to reference them in the same directory only by its basename
                    shutil.copy2(os.path.join(mediafolder, media_location), os.path.join(media_outdir, media_filename))

        return media_filename


class WhatsAppChatSessions(base.job.BaseModule):
    """ Returns all the available chat identifiers in a whatsapp database.

    The returned dictionary have a field mesage_group.
    """

    def run(self, path=None):
        self.check_params(path, check_path=True, check_path_exists=True)
        chatstorage_file = os.path.join(os.path.join(path, 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite'))
        if not base.utils.check_file(chatstorage_file):
            self.logger().warning("The file %s do not exists", chatstorage_file)
            return []
        conn = sqlite3.connect('file://{}?mode=ro'.format(chatstorage_file), uri=True)
        c = conn.cursor()
        for line in c.execute('SELECT DISTINCT ZCHATSESSION FROM ZWAMESSAGE'):
            yield(dict(message_group=line[0]))
        return []
