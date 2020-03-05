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
import csv
import sqlite3
import re
import biplist
import datetime
import base.job
from plugins.external.OSX_QuickLook_Parser import quicklook_parser_v_3_5mod
from plugins.external.ccl_asldb import ccl_asldb, OSX_asl_login_timeline
from plugins.common.RVT_files import GetFiles
from base.utils import check_folder
from plugins.external.PythonDsstore import dsstore
from base.commands import run_command
# import subprocess
# import fnmatch
# import sys
# from .Utils.macMRU import macMRU

# Preferences:
# https://github.com/ydkhatri/mac_apt/tree/master/plugins


class QuickLook(base.job.BaseModule):

    def run(self, path=""):
        """ Main function to extract quick look information

        """

        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        ql_path = self.myconfig("outdir")

        check_folder(ql_path)

        search = GetFiles(self.config, vss=self.myflag("vss"))

        ql_list = search.search("QuickLook.thumbnailcache$")

        for i in ql_list:
            self.logger().info("Extracting quicklook data from {}".format(i))
            out_path = os.path.join(ql_path, i.split("/")[-3])
            if not os.path.isdir(out_path):
                os.mkdir(out_path)
            quicklook_parser_v_3_5mod.process_database(os.path.join(self.myconfig('casedir'), i), out_path)
        self.logger().info("Done QuickLook")
        return []


class ASL(base.job.BaseModule):

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        info_path = self.myconfig('outdir')
        check_folder(info_path)
        search = GetFiles(self.config, vss=self.myflag("vss"))
        asl_files = list(search.search(r"var/log/asl/.*\.asl$"))

        # asl dump
        with open(os.path.join(info_path, "asldump.csv"), "w") as out_asl:
            writer = csv.writer(out_asl, delimiter="|", quotechar='"')
            headers = ["Timestamp", "Host", "Sender", "PID", "Reference Process", "Reference PID", "Facility", "Level", "Message", "Other details"]
            writer.writerow(headers)
            for file in asl_files:
                self.logger().info("Processing: {}".format(file))
                try:
                    f = open(os.path.join(self.myconfig('casedir'), file), "rb")
                except IOError as e:
                    self.logger().error("Could not open file '{}' ({}): Skipping this file".format(file, e))
                    continue

                try:
                    db = ccl_asldb.AslDb(f)
                except ccl_asldb.AslDbError as e:
                    self.logger().error("Could not read file as ASL DB '{}' ({}): Skipping this file".format(file, e))
                    f.close()
                    continue

                for record in db:
                    writer.writerow([record.timestamp.isoformat(), record.host, record.sender, str(record.pid), str(record.refproc), str(record.refpid), record.facility, record.level_str, record.message.replace(
                        "\n", " ").replace("\t", "    "), "; ".join(["{0}='{1}'".format(key, record.key_value_dict[key]) for key in record.key_value_dict]).replace("\n", " ").replace("\t", "    ")])
                f.close()

        asl_path = list(set(os.path.dirname(asl) for asl in asl_files))

        for path in asl_path:
            self.logger().info("Processing files from folder: {}".format(path))
            OSX_asl_login_timeline.__dowork__((os.path.join(self.myconfig('casedir'), path),), (os.path.join(self.myconfig('outdir'), "login_power.md"),))
        self.logger().info("Done ASL")
        return []


class FSEvents(base.job.BaseModule):

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        search = GetFiles(self.config, vss=self.myflag("vss"))
        parser = os.path.join(self.myconfig('rvthome'), "plugins/external/FSEventsParser/FSEParser_V4.0.py")
        fsevents = search.search(r"\.fseventsd$")

        fsevents_path = self.myconfig('outdir')
        check_folder(fsevents_path)

        python = self.myconfig('python', '/usr/bin/python')

        n = 1
        for f in fsevents:
            self.logger().info("Processing file {}".format(f))
            run_command([python, parser, "-c", "Report_{}".format(f.split('/')[-2]),
                         "-s", os.path.join(self.myconfig('casedir'), f), "-t", "folder", "-o", fsevents_path,
                         "-q", os.path.join(self.myconfig('rvthome'), "plugins/external/FSEventsParser/report_queries.json")])
            n += 1
        self.logger().info("Done FSEvents")
        return []


class Spotlight(base.job.BaseModule):

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        search = GetFiles(self.config, vss=self.myflag("vss"))
        parser = os.path.join(self.myconfig('rvthome'), "plugins/external/spotlight_parser/spotlight_parser.py")
        spotlight = search.search(r"/\.spotlight.*/store.db$")

        spotlight_path = self.myconfig('outdir')
        check_folder(spotlight_path)

        # TODO: adapt external spotlight_parser.py script to python3
        python = self.myconfig('python', '/usr/bin/python')

        n = 1
        errorlog = os.path.join(self.myconfig('sourcedir'), "{}_aux.log".format(self.myconfig('source')))
        with open(errorlog, 'a') as logfile:
            for f in spotlight:
                self.logger().info("Processing file {}".format(f))
                run_command([python, parser, os.path.join(self.myconfig('casedir'), f), spotlight_path, "-p", "spot-%s" % str(n)], stdout=logfile, stderr=logfile)
                n += 1
        self.logger().info("Spotlight done")
        return []


class KnowledgeC(base.job.BaseModule):
    # https://github.com/bolodev/osxripper/blob/master/plugins/osx/SystemKnowledgeC.py
    # Database columns do not match in recent versions

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        search = GetFiles(self.config, vss=self.myflag("vss"))
        knowledgec = search.search("/knowledgec.db$")

        knowledgec_path = self.myconfig('outdir')
        check_folder(knowledgec_path)

        for k in knowledgec:
            self.logger().info("Processing file {}".format(k))
            if k.find('/Users/') < 0:
                output = os.path.join(knowledgec_path, "private.txt")
            else:
                aux = re.search("/Users/([^/]+)", k)
                output = os.path.join(knowledgec_path, "{}.txt".format(aux.group(1)))

            with open(output, "w") as out:
                with sqlite3.connect('file://{}?mode=ro'.format(os.path.join(self.myconfig('casedir'), k)), uri=True) as conn:
                    conn.text_factory = str

                    c = conn.cursor()
                    c.execute('SELECT DISTINCT ZOBJECT.ZSTREAMNAME FROM ZOBJECT ORDER BY ZSTREAMNAME;')

                    for i in c.fetchall():
                        out.write("{}\n".format(i[0]))

                    c.execute('''SELECT datetime(ZOBJECT.ZCREATIONDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "ENTRY CREATION", CASE ZOBJECT.ZSTARTDAYOFWEEK
    WHEN "1" THEN "Sunday"
    WHEN "2" THEN "Monday"
    WHEN "3" THEN "Tuesday"
    WHEN "4" THEN "Wednesday"
    WHEN "5" THEN "Thursday"
    WHEN "6" THEN "Friday"
    WHEN "7" THEN "Saturday"
END "DAY OF WEEK",ZOBJECT.ZSECONDSFROMGMT/3600 AS "GMT OFFSET", datetime(ZOBJECT.ZSTARTDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "START",
datetime(ZOBJECT.ZENDDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "END", (ZOBJECT.ZENDDATE-ZOBJECT.ZSTARTDATE) as "USAGE IN SECONDS",
ZOBJECT.ZSTREAMNAME,ZOBJECT.ZVALUESTRING FROM ZOBJECT WHERE ZSTREAMNAME IS "/app/inFocus" ORDER BY "START";''')

                    out.write("\n\nENTRY CREATION|DAY OF WEEK|GMT OFFSET|START|END|USAGE IN SECONDS|ZSTREAMNAME|ZVALUESTRING\n")
                    for i in c.fetchall():
                        out.write("{}|{}|{}|{}|{}|{}|{}|{}\n".format(i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7]))

                    c.execute('''SELECT
datetime(ZOBJECT.ZCREATIONDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "ENTRY CREATION", ZOBJECT.ZSECONDSFROMGMT/3600 AS "GMT OFFSET",
CASE ZOBJECT.ZSTARTDAYOFWEEK
    WHEN "1" THEN "Sunday"
    WHEN "2" THEN "Monday"
    WHEN "3" THEN "Tuesday"
    WHEN "4" THEN "Wednesday"
    WHEN "5" THEN "Thursday"
    WHEN "6" THEN "Friday"
    WHEN "7" THEN "Saturday"
END "DAY OF WEEK", datetime(ZOBJECT.ZSTARTDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "START",
datetime(ZOBJECT.ZENDDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "END", (ZOBJECT.ZENDDATE-ZOBJECT.ZSTARTDATE) as "USAGE IN SECONDS", ZOBJECT.ZSTREAMNAME,
ZOBJECT.ZVALUESTRING, ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__ACTIVITYTYPE AS "ACTIVITY TYPE",
ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__TITLE as "TITLE", ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__USERACTIVITYREQUIREDSTRING as "ACTIVITY STRING",
datetime(ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__EXPIRATIONDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "EXPIRATION DATE"
FROM ZOBJECT left join ZSTRUCTUREDMETADATA on ZOBJECT.ZSTRUCTUREDMETADATA = ZSTRUCTUREDMETADATA.Z_PK WHERE ZSTREAMNAME is "/app/activity" or ZSTREAMNAME is "/app/inFocus"
ORDER BY "START";''')

                    out.write("\n\nENTRY CREATION|GMT OFFSET|DAY OF WEEK|START|END|USAGE IN SECONDS|ZSTREAMNAME|ZVALUESTRING|ACTIVITY TYPE|TITLE|ACTIVITY STRING|EXPIRATION DATE\n")
                    for i in c.fetchall():
                        out.write("{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n".format(i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], i[9], i[10], i[11]))

                    c.execute('''SELECT
datetime(ZOBJECT.ZCREATIONDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "ENTRY CREATION", CASE ZOBJECT.ZSTARTDAYOFWEEK
    WHEN "1" THEN "Sunday"
    WHEN "2" THEN "Monday"
    WHEN "3" THEN "Tuesday"
    WHEN "4" THEN "Wednesday"
    WHEN "5" THEN "Thursday"
    WHEN "6" THEN "Friday"
    WHEN "7" THEN "Saturday"
END "DAY OF WEEK", datetime(ZOBJECT.ZSTARTDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "START", datetime(ZOBJECT.ZENDDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "END",
(ZOBJECT.ZENDDATE-ZOBJECT.ZSTARTDATE) as "USAGE IN SECONDS", ZOBJECT.ZSTREAMNAME, ZOBJECT.ZVALUESTRING, ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__ACTIVITYTYPE AS "ACTIVITY TYPE",
ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__TITLE as "TITLE", ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__USERACTIVITYREQUIREDSTRING as "ACTIVITY STRING",
datetime(ZSTRUCTUREDMETADATA.Z_DKAPPLICATIONACTIVITYMETADATAKEY__EXPIRATIONDATE+978307200,'UNIXEPOCH', 'LOCALTIME') as "EXPIRATION DATE",
ZSTRUCTUREDMETADATA.Z_DKINTENTMETADATAKEY__INTENTCLASS as "INTENT CLASS", ZSTRUCTUREDMETADATA.Z_DKINTENTMETADATAKEY__INTENTVERB as "INTENT VERB",
ZSTRUCTUREDMETADATA.Z_DKINTENTMETADATAKEY__SERIALIZEDINTERACTION as "SERIALIZED INTERACTION", ZSOURCE.ZBUNDLEID FROM ZOBJECT
left join ZSTRUCTUREDMETADATA on ZOBJECT.ZSTRUCTUREDMETADATA = ZSTRUCTUREDMETADATA.Z_PK left join ZSOURCE on ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
WHERE ZSTREAMNAME is "/app/activity" or ZSTREAMNAME is "/app/inFocus" or ZSTREAMNAME is "/app/intents" ORDER BY "START";''')

                    out.write("\n\nENTRY CREATION|DAY OF WEEK|START|END|TITLE|ACTIVITY STRING|EXPIRATION DATE|INTENT CLASS|INTENT VERB|SERIALIZED INTERACTION|ZBUNDLEID\n")
                    for i in c.fetchall():
                        out.write("{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n".format(i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], i[9], i[10], i[11]))

        self.logger().info("Done parsing KnowledgeC")
        return []


class ParseDSStore(base.job.BaseModule):

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        search = GetFiles(self.config, vss=self.myflag("vss"))
        dsstore_files = search.search(r"/\.ds_store$")

        output1 = os.path.join(self.myconfig('outdir'), "dsstore_dump.txt")
        output2 = os.path.join(self.myconfig('outdir'), "dsstore.txt")

        with open(output1, 'w') as out1:
            filelist = set()
            n_stores = 0
            for dstores in dsstore_files:
                out1.write("{}\n-------------------------------\n".format(dstores))
                with open(os.path.join(self.myconfig('casedir'), dstores), "rb") as ds:
                    try:
                        d = dsstore.DS_Store(ds.read(), debug=False)
                        files = d.traverse_root()
                        for f in files:
                            filelist.add(os.path.join(os.path.dirname(dstores), f))
                            out1.write("%s\n" % f)
                    except Exception as exc:
                        self.logger().warning("Problems parsing file {}. Error: {}".format(dstores, exc))
                n_stores += 1
                out1.write("\n")

        self.logger().info("Founded {} .DS_Store files".format(n_stores))

        with open(output2, "w") as out:
            for f in sorted(filelist):
                out.write("%s\n" % f)
        self.logger().info("ParseDSStore Done")
        return []


class ParsePlist(base.job.BaseModule):

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        search = GetFiles(self.config, vss=self.myflag("vss"))
        plist_files = search.search(r"\.plist$")

        plist_num = 0
        with open(os.path.join(self.myconfig('outdir'), "plist_dump.txt"), 'wb') as output:
            for pl in plist_files:
                plist_num += 1
                output.write("{}\n-------------------------------\n".format(pl).encode())
                # try:
                #     text = subprocess.check_output(["plistutil", "-i", os.path.join(self.myconfig('mountdir'), pl)])
                #     output.write(text)
                #     output.write(b"\n\n")
                # except:
                #     self.logger().warning("Problems with file %s" % pl)
                #     output.write(b"\n\n")

                try:
                    plist = biplist.readPlist(os.path.join(self.myconfig('casedir'), pl))
                    output.write(self.pprint(plist) + b"\n\n")
                except (biplist.InvalidPlistException, biplist.NotBinaryPlistException):
                    self.logger().info("%s not a plist file or is corrupted" % pl)
                    output.write(b"\n\n")
                except Exception:
                    self.logger().info("Problems with file %s" % pl)

        self.logger().info("Founded {} plist files".format(plist_num))
        self.logger().info("Done parsing Plist")
        return []

    def pprint(self, data, indent=0):
        if type(data) == dict:
            text = b"    " * indent + b"{\n"
            for k in sorted(data.keys()):
                if type(data[k]) == dict or type(data[k]) == list:
                    text += b"    " * (indent + 1) + k.encode() + b": " + self.pprint(data[k], indent + 1) + b"\n"
                else:
                    text += b"    " * (indent + 1) + k.encode() + b": " + self.pprint(data[k], 0) + b"\n"
            text += b"    " * indent + b"}"
            return text
        elif type(data) == list:
            text = b"[\n"
            for k in data:
                text += self.pprint(k, indent + 1) + b"\n"
            text += b"    " * indent + b"]"
            return text
        elif type(data) == bytes:
            return b"    " * indent + data
        elif type(data) == str:
            return b"    " * indent + data.encode()
        else:
            return b"    " * indent + str(data).encode()


class MacMRU(base.job.BaseModule):

    def run(self, path=""):

        search = GetFiles(self.config, vss=self.myflag("vss"))
        users = search.search(r"p\d+(/root)?/Users/[^/]+$")
        mru_path = self.myconfig('outdir')
        check_folder(mru_path)

        parser = os.path.join(self.myconfig('rvthome'), "plugins/external/macMRU/macMRU.py")
        python3 = os.path.join(self.myconfig('rvthome'), '.venv/bin/python3')

        for user in users:
            self.logger().info("Extracting MRU info from user {}".format(os.path.basename(user)))
            with open(os.path.join(mru_path, '%s.txt' % os.path.basename(user)), 'w') as f:
                self.logger().debug("Generating file {}".format(os.path.join(mru_path, '%s.txt' % os.path.basename(user))))
                run_command([python3, parser, os.path.join(self.myconfig('casedir'), user)], stdout=f)

        self.logger().info("Done parsing MacMRU")
        return []
    #         fout = open(os.path.join(mru_path, '%s.txt' % os.path.basename(user)), 'w')
    #         sys.stdout = fout
    #         for root, dirs, filenames in os.walk(os.path.join(self.myconfig('mountdir'), user)):
    #             for f in filenames:
    #                 if f.endswith(".sfl") and not fnmatch.fnmatch(f, '*Favorite*.sfl') and not fnmatch.fnmatch(f, '*Project*.sfl') and not fnmatch.fnmatch(f, '*iCloudItems*.sfl'):
    #                     self.parseFile(macMRU.ParseSFL, os.path.join(root, f))
    #                 elif f.endswith(".sfl2") and not fnmatch.fnmatch(f, '*Favorite*.sfl2') and not fnmatch.fnmatch(f, '*Project*.sfl2') and not fnmatch.fnmatch(f, '*iCloudItems*.sfl2'):
    #                     self.parseFile(macMRU.ParseSFL2, os.path.join(root, f))
    #                 elif f.endswith("FavoriteVolumes.sfl2"):
    #                     self.parseFile(macMRU.ParseSFL2_FavoriteVolumes, os.path.join(root, f))
    #                 elif f.endswith(".LSSharedFileList.plist"):
    #                     self.parseFile(macMRU.ParseLSSharedFileListPlist, os.path.join(root, f))
    #                 elif f == "com.apple.finder.plist":
    #                     self.parseFile(macMRU.ParseFinderPlist, os.path.join(root, f))
    #                 elif f == "com.apple.sidebarlists.plist":
    #                     self.parseFile(macMRU.ParseSidebarlistsPlist, os.path.join(root, f))
    #                 elif f == "com.apple.recentitems.plist":
    #                     self.parseFile(macMRU.ParseRecentItemsPlist, os.path.join(root, f))
    #                 elif f.endswith(".securebookmarks.plist"):
    #                     self.parseFile(macMRU.ParseMSOffice2016Plist, os.path.join(root, f))
    #                 elif f == "com.microsoft.office.plist":
    #                     self.parseFile(macMRU.ParseMSOffice2011Plist, os.path.join(root, f))
    #                 elif f == "com.apple.spotlight.Shortcuts":
    #                     self.parseFile(macMRU.SpotlightShortcuts, os.path.join(root, f))
    #         fout.close()
    #     sys.stdout = sys.__stdout__

    # def parseFile(self, parser, file):
    #     print("==============================================================================")
    #     print("Parsing: %s" % file)
    #     parser(file)
    #     print("==============================================================================")


class BasicInfo(base.job.BaseModule):

    def run(self, path=""):

        with open(os.path.join(self.myconfig('outdir'), 'basic_info.md'), 'w') as out:
            self.logger().info("Extracting basic info")

            for p in sorted(os.listdir(self.myconfig('mountdir'))):
                base_path = os.path.join(self.myconfig('mountdir'), p)
                if len(os.listdir(base_path)) == 2 and os.path.isdir(os.path.join(base_path, "root")) and os.path.isdir(os.path.join(base_path, "private_dir")):
                    base_path = os.path.join(self.myconfig('mountdir'), p, "root")

                # version
                sysver = os.path.join(base_path, "System/Library/CoreServices/SystemVersion.plist")
                if not os.path.isfile(sysver):  # some APFS partitions have root or Private as root folders
                    base_path = os.path.join(self.myconfig('mountdir'), p, "root")
                    sysver = os.path.join(base_path, "System/Library/CoreServices/SystemVersion.plist")
                if not os.path.isfile(sysver):
                    continue

                out.write("# Information of partition {}\n".format(p))
                plist = biplist.readPlist(sysver)
                out.write("Product Name:\t\t{}\nProduct Build Version:\t{}\nProduct Version:\t{}\n".format(plist["ProductName"], plist["ProductBuildVersion"], plist["ProductVersion"]))

                # Install date
                try:
                    out.write("Install date:\t%s\n\n" % datetime.datetime.utcfromtimestamp(os.path.getmtime(os.path.join(base_path, "var/db/.AppleSetupDone"))).strftime("%Y-%m-%dT%H:%M:%SZ"))
                except Exception:
                    pass

                lastlog_file = os.path.join(base_path, "Library/Preferences/com.apple.loginwindow.plist")
                if os.path.isfile(lastlog_file):
                    plist = biplist.readPlist(lastlog_file)
                    out.write("Last User:\t{}\nLast User Name:\t{}\n\n".format(plist["lastUser"], plist["lastUserName"]))

                aux_path = os.path.join(base_path, "var/db/dslocal/nodes/Default/users")
                if os.path.isdir(aux_path):
                    out.write("User|Creation date|change pass date\n--|--|--\n")
                    for file in sorted(os.listdir(aux_path)):
                        if not file.startswith("_"):
                            table_data = [file[:-6], "", ""]
                            try:
                                plist = biplist.readPlist(os.path.join(aux_path, file))
                                pl2 = biplist.readPlistFromString(plist['accountPolicyData'][0])
                                if "creationTime" in pl2.keys():
                                    table_data[1] = datetime.datetime.utcfromtimestamp(pl2["creationTime"]).strftime("%Y-%m-%dT%H:%M:%SZ")
                                if "passwordLastSetTime" in pl2.keys():
                                    table_data[2] = datetime.datetime.utcfromtimestamp(pl2["passwordLastSetTime"]).strftime("%Y-%m-%dT%H:%M:%SZ")
                            except Exception:
                                pass
                            if table_data[1] != "" or table_data[2] != "":
                                out.write('{}|{}|{}\n'.format(table_data[0], table_data[1], table_data[2]))
                            else:
                                self.logger().warning("Problems extracting userinfo from file %s" % file)
                out.write('\n')

        self.logger().info("MacOS Basic Info done")
        return []


class NetworkUsage(base.job.BaseModule):

    def run(self, path=""):
        search = GetFiles(self.config, vss=self.myflag("vss"))
        nusage = search.search("/netusage.sqlite$")
        output = os.path.join(self.myconfig('outdir'), "network_usage.txt")

        with open(output, "w") as out:
            for k in nusage:
                self.logger().info("Extracting information of file {}".format(k))
                with sqlite3.connect('file://{}?mode=ro'.format(os.path.join(self.myconfig('casedir'), k)), uri=True) as conn:
                    conn.text_factory = str
                    c = conn.cursor()

                    out.write("{}\n------------------------------------------\n".format(k))
                    query = '''SELECT pk.z_name as item_type, na.zidentifier as item_name, na.zfirsttimestamp as first_seen_date, na.ztimestamp as last_seen_date,
rp.ztimestamp as rp_date, rp.zbytesin, rp.zbytesout FROM znetworkattachment as na LEFT JOIN z_primarykey pk ON na.z_ent = pk.z_ent
LEFT JOIN zliverouteperf rp ON rp.zhasnetworkattachment = na.z_pk ORDER BY pk.z_name, zidentifier, rp_date desc;'''.replace('\n', ' ').upper()
                    c.execute(query)

                    out.write("\n\nitem_type|item_name|first_seen_date|last_seen_date|rp_date|ZBYTESIN|ZBYTESOUT\n--|--|--|--|--|--|--\n")
                    for i in c.fetchall():
                        out.write("{}|{}|{}|{}|{}|{}|{}\n".format(i[0], i[1], i[2], i[3], i[4], i[5], i[6]))

                    query = '''SELECT pk.z_name as item_type ,p.zprocname as process_name, p.zfirsttimestamp as first_seen_date, p.ztimestamp as last_seen_date,
lu.ztimestamp as usage_since, lu.zwifiin, lu.zwifiout, lu.zwiredin, lu.zwiredout, lu.zwwanin, lu.zwwanout FROM zliveusage lu
LEFT JOIN zprocess p ON p.z_pk = lu.zhasprocess LEFT JOIN z_primarykey pk ON p.z_ent = pk.z_ent ORDER BY process_name;'''.replace('\n', ' ').upper()
                    c.execute(query)

                    out.write("\n\nitem_type|process_name|first_seen_date|last_seen_date|usage_since|ZWIFIIN|ZWIFIOUT|ZWIREDIN|ZWIREDOUT|ZWWANIN|ZWANOUT\n--|--|--|--|--|--|--|--|--|--|--\n")
                    for i in c.fetchall():
                        out.write("{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n".format(i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], i[9], i[10]))
                    out.write("\n")
                    c.close()

        self.logger().info("Done parsing netusage.sqlite")
        return []


class Quarantine(base.job.BaseModule):

    def run(self, path=""):
        search = GetFiles(self.config, vss=self.myflag("vss"))
        quarantine = search.search("/com.apple.LaunchServices.QuarantineEventsV2$")

        output = os.path.join(self.myconfig('outdir'), "quarantine.txt")

        with open(output, "w") as out:
            for k in quarantine:
                self.logger().info("Extracting information of file {}".format(k))
                with sqlite3.connect('file://{}?mode=ro'.format(os.path.join(self.myconfig('casedir'), k)), uri=True) as conn:
                    conn.text_factory = str
                    c = conn.cursor()

                    out.write("{}\n------------------------------------------\n".format(k))
                    query = '''SELECT LSQuarantineEventIdentifier as id, LSQuarantineTimeStamp as ts, LSQuarantineAgentBundleIdentifier as bundle,
LSQuarantineAgentName as agent_name, LSQuarantineDataURLString as data_url,
LSQuarantineSenderName as sender_name, LSQuarantineSenderAddress as sender_add, LSQuarantineTypeNumber as type_num,
LSQuarantineOriginTitle as o_title, LSQuarantineOriginURLString as o_url, LSQuarantineOriginAlias as o_alias
FROM LSQuarantineEvent  ORDER BY ts;'''.replace('\n', ' ')
                    c.execute(query)

                    out.write("\n\nid|ts|bundle|agent_name|data_url|sender_name|sender_add|type_num|o_title|o_url|o_alias\n--|--|--|--|--|--|--|--|--|--|--\n")
                    for i in c.fetchall():
                        out.write("{}|{}|{}|{}|{}|{}|{}\n".format(i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], i[9], i[10]))
                    out.write("\n")
                    c.close()

        self.logger().info("Done parsing QuarantineEvents")
        return []


class Network(base.job.BaseModule):

    def run(self, path=""):
        self.GetNetworkInterfaceInfo()
        self.GetNetworkInterface2Info()
        self.GetDhcpInfo()
        self.ProcessActiveDirectoryPlist()
        return []

    def GetNetworkInterfaceInfo(self):
        '''Read interface info from NetworkInterfaces.plist
        modified from networking plugin from https://github.com/ydkhatri/mac_apt'''

        search = GetFiles(self.config, vss=self.myflag("vss"))
        network = search.search("/Library/Preferences/SystemConfiguration/NetworkInterfaces.plist$")
        classes = ['Active', 'BSD Name', 'IOBuiltin', 'IOInterfaceNamePrefix', 'IOInterfaceType', 'IOInterfaceUnit', 'IOPathMatch', 'SCNetworkInterfaceType']

        out = open(os.path.join(self.myconfig('outdir'), 'Network_Interfaces.csv'), 'w')
        writer = csv.writer(out, delimiter="|", quotechar='"')
        headers = ["Category", "Active", "BSD Name", "IOBuiltin", "IOInterfaceNamePrefix", "IOInterfaceType",
                   "IOInterfaceUnit", "IOMACAddress", "IOPathMatch", "SCNetworkInterfaceInfo", "SCNetworkInterfaceType", "Source"]
        writer.writerow(headers)

        for net in network:
            self.logger().debug("Trying to read {}".format(net))
            # try:
            plist = biplist.readPlist(os.path.join(self.myconfig('casedir'), net))
            try:
                self.logger().info("Model = %s" % plist['Model'])
            except Exception:
                pass
            for category, cat_array in plist.items():  # value is another array in this dict
                if not category.startswith('Interface'):
                    if category != 'Model':
                        self.logger().debug('Skipping %s' % category)
                    continue
                for interface in cat_array:
                    interface_info = {'Category': category, 'Source': net}
                    for c in classes:
                        interface_info[c] = ""
                    for item, value in interface.items():
                        if item in classes:
                            interface_info[item] = value
                        elif item == 'IOMACAddress':  # convert binary blob to MAC address
                            data = value.hex().upper()
                            data = [data[2 * n:2 * n + 2] for n in range(6)]
                            interface_info[item] = ":".join(data)
                        elif item == 'SCNetworkInterfaceInfo':
                            try:
                                interface_info['SCNetworkInterfaceInfo'] = value['UserDefinedName']
                            except Exception:
                                pass
                        else:
                            self.logger().info("Found unknown item in plist: ITEM=" + item + " VALUE=" + str(value))
                    writer.writerow([interface_info[c] for c in headers])
        out.close()

    def GetNetworkInterface2Info(self):
        '''Read interface info from /Library/Preferences/SystemConfiguration/preferences.plist

        Based on mac_apt plugin from https://github.com/ydkhatri/mac_apt
        '''
        search = GetFiles(self.config, vss=self.myflag("vss"))
        network = search.search("/Library/Preferences/SystemConfiguration/preferences.plist$")

        with open(os.path.join(self.myconfig('outdir'), 'Network_Details.csv'), 'w') as out:
            writer = csv.writer(out, delimiter="|", quotechar='"')
            headers = ["UUID", "IPv4.ConfigMethod", "IPv6.ConfigMethod", "DeviceName", "Hardware", "Type", "SubType",
                       "UserDefinedName", "Proxies.ExceptionsList", "SMB.NetBIOSName", "SMB.Workgroup", "PPP", "Modem"]
            writer.writerow(headers)
            for net in network:
                plist = biplist.readPlist(os.path.join(self.myconfig('casedir'), net))
                for uuid in plist['NetworkServices'].keys():
                    data = [uuid] + [""] * 12
                    if 'IPv4' in plist['NetworkServices'][uuid].keys():
                        data[1] = plist['NetworkServices'][uuid]['IPv4']['ConfigMethod']
                    if 'IPv6' in plist['NetworkServices'][uuid].keys():
                        data[2] = plist['NetworkServices'][uuid]['IPv6']['ConfigMethod']
                    if 'Interface' in plist['NetworkServices'][uuid].keys():
                        data[3] = plist['NetworkServices'][uuid]['Interface']['DeviceName']
                        data[4] = plist['NetworkServices'][uuid]['Interface']['Hardware']
                        data[5] = plist['NetworkServices'][uuid]['Interface']['Type']
                        if 'SubType' in plist['NetworkServices'][uuid]['Interface'].keys():
                            data[6] = plist['NetworkServices'][uuid]['Interface']['SubType']
                        data[7] = plist['NetworkServices'][uuid]['Interface']['UserDefinedName']

                    if 'Proxies' in plist['NetworkServices'][uuid].keys() and 'ExceptionsList' in plist['NetworkServices'][uuid]['Proxies'].keys():
                        data[8] = ",".join(plist['NetworkServices'][uuid]['Proxies']['ExceptionsList'])
                    if 'SMB' in plist['NetworkServices'][uuid].keys():
                        try:
                            data[9] = plist['NetworkServices'][uuid]['SMB']['NetBIOSName']
                            data[10] = plist['NetworkServices'][uuid]['SMB']['Workgroup']
                        except Exception:
                            pass
                    if 'PPP' in plist['NetworkServices'][uuid].keys():
                        data[11] = str(plist['NetworkServices'][uuid]['PPP'])
                    if 'Modem' in plist['NetworkServices'][uuid].keys():
                        data[12] = str(plist['NetworkServices'][uuid]['Modem'])
                    writer.writerow(data)

    def GetDhcpInfo(self):
        '''Read dhcp leases & interface entries

           Based on mac_apt plugin from https://github.com/ydkhatri/mac_apt
        '''
        search = GetFiles(self.config, vss=self.myflag("vss"))
        interfaces_path = search.search("/private/var/db/dhcpclient/leases$")

        out = open(os.path.join(self.myconfig('outdir'), 'Network_DHCP.csv'), 'w')
        writer = csv.writer(out, delimiter="|", quotechar='"')
        headers = ["Interface", "MAC_Address", "IPAddress", "LeaseLength", "LeaseStartDate", "PacketData", "RouterHardwareAddress", "RouterIPAddress", "SSID", "Source"]
        writer.writerow(headers)

        for interface in interfaces_path:
            for name in sorted(os.listdir(os.path.join(self.myconfig('casedir'), interface))):
                if name.find(",") > 0:
                    # Process plist
                    name_no_ext = os.path.splitext(name)[0]  # not needed as there is no .plist extension on these files
                    if_name, mac_address = name_no_ext.split(",")
                    self.logger().info("Found mac address = {} on interface {}".format(mac_address, if_name))

                    self.logger().debug("Trying to read {}".format(name))

                    plist = biplist.readPlist(os.path.join(self.myconfig('casedir'), interface, name))
                    interface_info = {}
                    for c in headers:
                        interface_info[c] = ""
                    interface_info['Source'] = os.path.join('/private/var/db/dhcpclient/leases', name)
                    interface_info['Interface'] = if_name
                    interface_info['MAC_Address'] = mac_address

                    for item, value in plist.items():
                        if item in ('IPAddress', 'LeaseLength', 'LeaseStartDate', 'RouterIPAddress', 'SSID'):
                            interface_info[item] = value
                        elif item == 'RouterHardwareAddress':  # convert binary blob to MAC address
                            data = value.hex().upper()
                            data = [data[2 * n:2 * n + 2] for n in range(6)]
                            interface_info[item] = ":".join(data)
                        elif item == 'PacketData':
                            interface_info['PacketData'] = value.hex().upper()
                        else:
                            self.logger().info("Found unknown item in plist: ITEM=" + item + " VALUE=" + str(value))
                    writer.writerow([interface_info[c] for c in headers])
                else:
                    self.logger().info("Found unexpected file, not processing /private/var/db/dhcpclient/leases/{} size={}".format(name, str(interface['size'])))
            # Done processing interfaces!
        out.close()

    def ProcessActiveDirectoryPlist(self):
        '''
        Extract active directory artifacts

        Based on mac_apt plugin from https://github.com/ydkhatri/mac_apt
        '''
        search = GetFiles(self.config, vss=self.myflag("vss"))
        network_paths = search.search("/Library/Preferences/OpenDirectory/Configurations/Active Directory$")

        out = open(os.path.join(self.myconfig('outdir'), 'Domain_ActiveDirectory.csv'), 'w')
        writer = csv.writer(out, delimiter="|", quotechar='"')
        headers = ["node name", "trustaccount", "trustkerberosprincipal", "trusttype", "allow multi-domain", "cache last user logon", "domain", "forest", "trust domain", "source"]
        writer.writerow(headers)

        for plist_path in network_paths:
            active_directory = {'source': plist_path}
            for archive in sorted(os.listdir(os.path.join(self.myconfig('casedir'), plist_path))):
                plist = biplist.readPlist(os.path.join(self.myconfig('casedir'), plist_path, archive))
                try:
                    for item, value in plist.items():
                        if item in ['node name', 'trustaccount', 'trustkerberosprincipal', 'trusttype']:
                            active_directory[item] = value
                    ad_dict = plist['module options']['ActiveDirectory']
                    for item, value in ad_dict.items():
                        if item in ['allow multi-domain', 'cache last user logon', 'domain', 'forest', 'trust domain']:
                            active_directory[item] = value
                except Exception:
                    self.logger().error('Error reading plist %s' % os.path.join(plist_path, archive))
                writer.writerow([active_directory[d] for d in headers])
        out.close()
        return[]


class ParseUnifiedLogReader(base.job.BaseModule):

    def run(self, path=""):
        if not os.path.isdir(self.myconfig('mountdir')):
            raise base.job.RVTError("Folder {} not exists".format(self.myconfig('mountdir')))

        search = GetFiles(self.config, vss=self.myflag("vss"))
        parser = os.path.join(self.myconfig('rvthome'), "plugins/external/UnifiedLogReader/scripts/UnifiedLogReader.py")
        uuidtext = search.search("/var/db/uuidtext$")
        timesync = search.search("/var/db/diagnostics/timesync$")
        diagnostics = search.search("/var/db/diagnostics$")

        ulr_path = self.myconfig('outdir')
        check_folder(ulr_path)

        if not uuidtext or not timesync or not diagnostics:
            return []

        python3 = '/usr/bin/python3'

        try:
            run_command([python3, parser, os.path.join(self.myconfig('casedir'), uuidtext[0]), os.path.join(self.myconfig('casedir'), timesync[0]), os.path.join(self.myconfig('casedir'), diagnostics[0]), ulr_path, "-l", "WARNING"])
        except Exception as exc:
            self.logger().error('Problems with UnifiedLogReader.py. Error:'.format(exc))
        self.logger().info("Done parsing UnifiedLogReader")
        return []
