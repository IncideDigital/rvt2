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


"""
File for conducting a coherence analysis on WhatsApps
"""

import sqlite3 as sq
import math
import datetime
import os
import os.path
import logging
import biplist
import plugins.ios


class AdvWhatsapps(plugins.ios.IOSModule):
    """
    Class responsible for conducting the coherence analysis on WhatsApps
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('extract_path', os.path.join(self.myconfig('sourcedir'), 'mnt', 'p01'))

    def connect(self):
        extract_path = self.myconfig('extract_path')
        storage = os.path.join(extract_path, 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared', 'ChatStorage.sqlite')
        searchV3 = os.path.join(extract_path, 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared', 'ChatSearchV3.sqlite')
        search = os.path.join(extract_path, 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared', 'ChatSearch.sqlite')
        if not os.path.isfile(storage):
            logging.error("The file ChatStorage.sqlite does not exist")
            return (None, None)

        if os.path.exists(searchV3):
            return (sq.connect('file://' + storage + '?mode=ro', uri=True), sq.connect('file://' + searchV3 + '?mode=ro', uri=True))
        else:
            return (sq.connect('file://' + storage + '?mode=ro', uri=True), sq.connect('file://' + search + '?mode=ro', uri=True))

    def get_tables(self, con_storage, con_search, out):
        cur_storage = con_storage.cursor()
        cur_search = con_search.cursor()

        cur_storage.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        cur_search.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")

        tablesStorage = (cur_storage.fetchall())
        tablesSearch = (cur_search.fetchall())

        out.write(tablesStorage, "\n")
        out.write(tablesSearch)

    def get_items_text(self, con_storage, con_search):
        cur_storage = con_storage.cursor()
        cur_search = con_search.cursor()

        cur_storage.execute("SELECT ZWAMESSAGE.ZDOCID, ZWAMESSAGE.Z_PK, ZWAMESSAGE.ZTEXT from ZWAMESSAGE where ZWAMESSAGE.ZMESSAGETYPE=0")
        cur_search.execute("SELECT docs_content.docid, docs_content.c2contents from docs_content")

        items_storage = {}
        items_search = {}

        for docid, pk, text in cur_storage.fetchall():
            items_storage[docid] = (pk, text)
        for k, l in cur_search.fetchall():
            items_search[k] = l

        return (items_search, items_storage)

    def get_items_date(self, con_storage, con_search):
        cur_storage = con_storage.cursor()
        cur_search = con_search.cursor()

        cur_storage.execute("SELECT ZWAMESSAGE.ZDOCID, ZWAMESSAGE.Z_PK, ZWAMESSAGE.ZMESSAGEDATE+978307200 from ZWAMESSAGE where ZWAMESSAGE.ZDOCID not NULL and ZWAMESSAGE.ZDOCID != 0")
        cur_search.execute("SELECT metadata.docID, metadata.date+978307200 from metadata")

        items_storage = {}
        items_search = {}

        for docid, pk, date in cur_storage.fetchall():
            items_storage[docid] = (pk, date)
        for k, l in cur_search.fetchall():
            items_search[k] = l

        return (items_search, items_storage)

    def get_items_count(self, con_storage):
        cur_storage = con_storage.cursor()

        cur_storage.execute("SELECT ZWAMESSAGE.ZCHATSESSION, count(*), ZWACHATSESSION.ZMESSAGECOUNTER, ZWACHATSESSION.ZCONTACTJID from ZWAMESSAGE inner join ZWACHATSESSION on ZWACHATSESSION.Z_PK = ZWAMESSAGE.ZCHATSESSION  where ZWAMESSAGE.ZCHATSESSION not NULL GROUP BY ZWAMESSAGE.ZCHATSESSION")

        items_storage = cur_storage.fetchall()
        return (items_storage)

    def compare_text(self, items_search, items_storage, out):
        """ Compare text by id between ChatStorage.sqlite and ChatSearch.sqlite. Write differences"""
        out.write("\n=====================================\n")
        out.write("Comparing text message with respect id...\n\n")

        i = 0
        for key in items_storage.keys():
            if key in items_search.keys() and items_search[key] != items_storage[key][1]:
                i = i + 1
                out.write("{}: Messages with id {} and messageid {}, are differents from BBDD ChatStorage.sqlite and ChatSearchV3.sqlite.\n\t In ChatSearchV3.sqlite appears:{}\n\t In ChatStorage.sqlite appears:{}\n".format(str(i), str(key), str(items_storage[key][0]), str(items_search[key]), str(items_storage[key][1])))

        if i == 0:
            out.write("All text messages MATCHES in TEXT and ID from both BBDD: ChatStorage.sqlite y ChatSearchV3.sqlite")
            out.write("\n=====================================\n")
        else:
            out.write("All text menssages, except %s, MATCHES in TEXT and ID from both BBDD: ChatStorage.sqlite y ChatSearchV3.sqlite" % str(i))
            out.write("\n=====================================\n")

    def compare_date(self, items_search, items_storage, out):
        """ Compare dates by id between ChatStorage.sqlite and ChatSearch.sqlite. Write messages with dates differing in more than 10sec"""
        out.write("\n=====================================\n")
        out.write("Comparing messages dates with respect id (using tdelta = 10s)...\n\n")

        i = 0
        for key in items_storage.keys():
            if key in items_search.keys() and (math.fabs(items_search[key] - items_storage[key][1]) > 10):
                i = i + 1
                out.write("{}: Message dates with docid {} and messageid {}, are different from BBDD ChatStorage.sqlite and ChatSearchV3.sqlite.\n\t In ChatSearchV3.sqlite appears: {}\n\t In ChatStorage.sqlite appears: {}\n".format(str(i), str(key), str(items_storage[key][0]), str(datetime.datetime.fromtimestamp(items_search[key]).strftime('%Y-%m-%d %H:%M:%S')), str(datetime.datetime.fromtimestamp(items_storage[key][1]).strftime('%Y-%m-%d %H:%M:%S'))))

        if i == 0:
            out.write("All message dates MATCHES in DATE and ID in both: ChatStorage.sqlite and ChatSearchV3.sqlite")
            out.write("\n=====================================\n")
        else:
            out.write("All message dates, except %s, MATCHES in DATE and ID in both BBDD: ChatStorage.sqlite and ChatSearchV3.sqlite" % str(i))
            out.write("\n=====================================\n")

    def blacklist(self, con_storage, out):
        cur_storage = con_storage.cursor()

        cur_storage.execute("SELECT ZWABLACKLISTITEM.ZJID, ZWAPROFILEPUSHNAME.ZPUSHNAME from ZWABLACKLISTITEM inner join ZWAPROFILEPUSHNAME on ZWABLACKLISTITEM.ZJID = ZWAPROFILEPUSHNAME.ZJID UNION ALL SELECT ZWABLACKLISTITEM.ZJID, NULL from ZWABLACKLISTITEM")

        contactsBlock = cur_storage.fetchall()

        list = []
        block = {}

        for key, value in contactsBlock:
            if key not in list:
                list.append(key)
                block[key] = value

        out.write("\n=====================================\n")
        out.write("Blocked contacts:\n\n")
        for key, value in block.items():
            out.write('{} : {}\n'.format(key, value))
        out.write("=====================================\n")

    def last_backup(self, out):
        """ Show last backup date. All message from this date on should be considered unmodified"""
        item = ''
        try:
            pl = biplist.readPlist(os.path.join(self.myconfig('extract_path'), 'Info.plist'))
            item = pl.get("Last Backup Date", '')
        except Exception as exc:
            self.logger().info('Unable to parse Info.plist. Err: {}'.format(exc))
        out.write("\n{}\n".format('=' * 60))
        out.write("Last Backup Date: \t\t{}\n{}\n".format(str(item), '=' * 60))

        item = ''
        try:
            pl2 = biplist.readPlist(os.path.join(self.myconfig('extract_path'), 'AppDomainGroup-group.net.whatsapp.WhatsApp.shared', 'Library', 'Preferences', 'group.net.whatsapp.WhatsApp.shared.plist'))
            item = pl2.get("AutoBackupCustom", '')
            item2 = pl2.get('lastAutoBackupDate', '')
        except Exception as exc:
            self.logger().info('Unable to parse WhatsApp.shared.plist. Err: {}'.format(exc))
        out.write("Last Whatsapp CustomBakup Date: {}\n{}\n".format(str(item), '=' * 60))
        out.write("Last Whatsapp AutoBakup Date: \t{}\n{}\n".format(str(item2), '=' * 60))

    def compare_count(self, items_storage, out):
        # TODO: document why a difference of 1 is allowed
        out.write("\n=====================================\n")
        out.write("Comparing message number of ZMESSAGECOUNTER with sum of messages per conversation...\n\n")
        out.write("(CHATSESSION, COUNT, ZMESSAGECOUNTER, CONTACT)")

        for item in items_storage:
            if item[2] - item[1] > 2 and item[3].find("status") == -1:
                out.write("%s\n" % str(item))

        out.write("=====================================\n")

    def deleted_items(self, con_storage, out):
        cur_storage = con_storage.cursor()

        cur_storage.execute("SELECT ZWACHATSESSION.ZREMOVED, ZWACHATSESSION.ZCONTACTJID, ZWACHATSESSION.ZPARTNERNAME from ZWACHATSESSION where ZWACHATSESSION.ZREMOVED = 1")

        deleted = cur_storage.fetchall()

        out.write("\n=====================================\n")
        out.write("In the nexts conversations appears ZREMOVED = 1 flag ...\n\n")
        out.write("(ZREMOVED, CONTACT, CONTACT NAME)")

        for item in deleted:
            out.write(str(item) + "\n")

        out.write("\n=====================================\n")

    def adv_whatsapp(self):
        outfilename = self.myconfig('outfile')
        if os.path.isfile(outfilename):
            os.remove(outfilename)
        out = open(outfilename, 'w')

        con_storage, con_search = self.connect()
        # get_tables(con_storage, con_search, out)
        self.last_backup(out)
        self.blacklist(con_storage, out)

        items_search, items_storage = self.get_items_text(con_storage, con_search)
        self.compare_text(items_search, items_storage, out)

        items_search, items_storage = self.get_items_date(con_storage, con_search)
        self.compare_date(items_search, items_storage, out)

        items_storage = self.get_items_count(con_storage)
        self.compare_count(items_storage, out)

        self.deleted_items(con_storage, out)

        out.close()
        con_storage.close()
        con_search.close()
        logging.info('WhatsApp\'s coherence analysis exported at %s', outfilename)

    def run(self, path):
        self.adv_whatsapp()
        return []
