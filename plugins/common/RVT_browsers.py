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


# Uses an adapted version of safari_parser_v1.1.py de arizona4n6@gmail.com (Mari DeGrazia)
# Uses an adapted version of BinaryCookieReader: developed by Satishb3: http://www.securitylearn.net

import os
import re
import shutil
import subprocess
import tempfile
import datetime
import biplist
import binascii
from struct import unpack
from io import BytesIO
from time import strftime, gmtime

import base.job
from base.commands import run_command, yield_command


def convert_absolute(mac_absolute_time):
    """ Convert mac absolute time (seconds from 1/1/2001) to human readable """
    try:
        bmd = datetime.datetime(2001, 1, 1, 0, 0, 0)
        humantime = bmd + datetime.timedelta(0, mac_absolute_time)
    except Exception:
        return("Error on conversion")
    return(datetime.datetime.strftime(humantime, "%Y-%m-%dT%H:%M:%SZ"))


class Edge(base.job.BaseModule):
    """ Generate Internet Explorer 10+ / Microsoft Edge web browsing or cookies history """

    def read_config(self):
        super().read_config()
        self.set_default_config('information', 'history')

    def run(self, path):
        self.info = self.myconfig('information', 'history')
        if self.info not in ['history', 'cookies', 'downloads']:
            raise ValueError('Invalid information kind {} to extract for edge artifacts'.format(self.info))

        esedbexport = self.config.config['plugins.common'].get('esedbexport', 'esedbexport')

        try:
            webcache_dir = tempfile.mkdtemp(suffix="_WebCacheV0")
            run_command([esedbexport, "-t", os.path.join(webcache_dir, "db"), path], stderr=subprocess.DEVNULL)
            self.webcache_dir_export = os.path.join(webcache_dir, "db.export")
            if not os.path.exists(self.webcache_dir_export):
                raise base.job.RVTError('esedbexport could not create db.export')
            self.get_ids()

            for info in self.parse_export():
                yield info
        finally:
            shutil.rmtree(webcache_dir)

        return[]

    def convert_date_format(self, string_date):
        return datetime.datetime.strptime(string_date[:-3], "%b %d, %Y %H:%M:%S.%f").strftime('%Y-%m-%d T%H:%M:%SZ')

    def get_ids(self):
        self.ids = []
        for filename in filter(lambda f: f.startswith("Containers"), os.listdir(self.webcache_dir_export)):
            with open(os.path.join(self.webcache_dir_export, filename), "r") as db_export:
                line = db_export.readline().split("\t")
                cont_id_pos = line.index("ContainerId")
                name_pos = line.index("Name")
                for line in db_export:
                    line = line.split("\t")
                    if self.info == 'history' and (line[name_pos].startswith("MSHist") or line[name_pos].startswith("History")):
                        self.ids.append(line[cont_id_pos])
                    elif self.info == 'cookies' and line[name_pos].startswith("Cookies"):
                        self.ids.append(line[cont_id_pos])
                    elif self.info == 'downloads' and line[name_pos].startswith("iedownload"):
                        self.ids.append(line[cont_id_pos])

    def parse_export(self):
        fields = {'history': {'AccessedTime': 'last_visit', 'ModifiedTime': 'modified'},
                  'cookies': {'AccessedTime': 'accessed', 'CreationTime': 'creation', 'ExpiryTime': 'expires'},
                  'downloads': {'AccessedTime': 'start', 'SyncTime': 'end', 'ModifiedTime': 'modified'}}
        fields_pos = {}

        for filename in os.listdir(self.webcache_dir_export):
            aux = re.search(r"Container_(\d+)\.", filename)
            if not (aux and aux.group(1) in self.ids):
                continue
            with open(os.path.join(self.webcache_dir_export, filename), "r") as db_export:
                line = db_export.readline().split("\t")
                for element in line:
                    if element in fields[self.info].keys() or element == 'Url' or element.startswith('ResponseHeaders') or element == 'AccessCount':
                        fields_pos[element.rstrip()] = line.index(element)

                for line in db_export:
                    line = line.split("\t")
                    result = {name: self.convert_date_format(line[fields_pos[elem]]) for elem, name in fields[self.info].items()}
                    real_url = '@'.join(line[fields_pos["Url"]].split('@')[1:])
                    result.update({'url': real_url})
                    result.update({'visit_count': line[fields_pos['AccessCount']]})
                    if 'Filename' in fields_pos.keys():
                        result.update({'path': line[fields_pos['Filename']], 'size': line[fields_pos['FileSize']], 'url': line[fields_pos['Url']]})
                    if 'ResponseHeaders' in fields_pos.keys() and self.info == 'downloads':
                        data = line[fields_pos['ResponseHeaders']]
                        var_aux = {}
                        var_aux['FileSize'] = self.reverse_hex_size(data, 144, 160)
                        # Decode hex part. Replace errors
                        data = binascii.unhexlify(data[688:]).decode('utf-16', errors='replace')
                        data = data.split('\x00')
                        var_aux['path'] = data[-2].replace('\\', '/')
                        var_aux['url'] = data[-3]
                        result.update({'path': var_aux['path'], 'url': var_aux['url'], 'size': var_aux['FileSize']})
                    yield result

    def reverse_hex_size(self, HEXVAL, init, end):
        hexVals = [HEXVAL[i:i + 2] for i in range(init, end, 2)]
        reversedHexVals = hexVals[::-1]
        return int(''.join(reversedHexVals), 16)


class InternetExplorer(base.job.BaseModule):
    """ Generate Internet Explorer web browsing history """

    def run(self, path):
        msiecfexport = self.config.config['plugins.common'].get('msiecfexport', 'msiecfexport')
        export = yield_command([msiecfexport, path], stderr=subprocess.DEVNULL, logger=self.logger())

        primary_secondary_time = "{} time".format('Secondary' if path.find("MSHist") > -1 else 'Primary')
        regex = re.compile(r"([^:]+):\s(.*)")
        entries = dict()

        for line in export:
            if len(line) < 2:
                if "Location" in entries.keys():
                    yield {'last_visit': entries[primary_secondary_time],
                           'last_checked': entries["Last checked time"],
                           'url': entries["Location"]}
                    entries = dict()
                    continue

            aux = regex.match(line)
            if aux and aux.group(1).strip() in ["Location", "Primary time", "Secondary time", "Last checked time"]:
                entries[aux.group(1).strip()] = aux.group(2)

        return []


class Safari(base.job.BaseModule):
    """ Generate Safari web browsing history, cookies and downloads """

    def read_config(self):
        super().read_config()
        self.set_default_config('information', 'history')

    def run(self, path):
        self.info = self.myconfig('information')
        if self.info not in ['history', 'cookies', 'downloads']:
            raise ValueError('Invalid information kind {} to extract for safari artifacts'.format(self.info))

        parser_functions = {'history': self.history_plist,
                            'downloads': self.downloads,
                            'cookies': self.cookies}

        for i in parser_functions[self.info](path):
            yield i

    def history_plist(self, path):
        history_count = 0
        plist = biplist.readPlist(path)

        # start at the root
        for key, value in plist.items():
            # go through the webhistory dictionary first
            if key != "WebHistoryDates":
                continue
            # loop through each history entry
            for history_entry in value:
                result = {"last_visit": "", "url": "", "title": "", "redirect_urls": ""}
                history_count += 1
                # for whatever stupid reason, the key is blank for the URL in the plist file
                URL = history_entry[""]

                if "lastVisitedDate" in history_entry:
                    lastVisitedDate = history_entry["lastVisitedDate"]
                    lastVisitedDate = int(lastVisitedDate[:-2])
                    lastVisitedDate = convert_absolute(lastVisitedDate)
                else:
                    lastVisitedDate = ""

                result['last_visit'] = lastVisitedDate
                result['url'] = str(URL)

                if "title" in history_entry:
                    try:
                        result['title'] = str(history_entry["title"])
                    except Exception:
                        title = history_entry["title"]
                        result['title'] = title.encode("utf-8")

                result['redirect_urls'] = ' | '.join([url for url in history_entry["redirectURLs"] if "redirectURLs" in history_entry])

                yield result

    def downloads(self, path):
        download_count = 0
        plist = biplist.readPlist(path)

        field_keys = {"url": "DownloadEntryURL",
                      "path": "DownloadEntryPath",
                      "bytes_so_far": "DownloadEntryProgressBytesSoFar",
                      "total_to_load": "DownloadEntryProgressTotalToLoad"}

        for key, value in plist.items():
            if key == "DownloadHistory":
                # loop through each topsite entry
                for downloads in value:
                    result = {k: '' for k in field_keys}

                    for out_field, in_field in field_keys.items():
                        try:
                            result[out_field] = str(downloads[in_field])
                        except Exception:
                            pass

                    yield result
                    download_count += 1

    def cookies(self, path):
        flag_names = {0: '', 1: 'Secure', 4: 'HttpOnly', 5: 'Secure; HttpOnly'}
        output_fields = ["creation", "expires", "url", "path", "cookie_name", "cookie_value", "flag"]
        transform = {'Domain': 'url', 'Path': 'path', 'Name': 'cookie_name', 'Value': 'cookie_value'}

        with open(path, 'rb') as binary_file:
            file_header = binary_file.read(4)  # File Magic String:cook

            if file_header != b'cook':
                raise ValueError("{} not recognized as Cookies.binarycookie file".format(path))

            num_pages = unpack('>i', binary_file.read(4))[0]  # Number of pages in the binary file: 4 bytes

            page_sizes = []
            for np in range(num_pages):
                page_sizes.append(unpack('>i', binary_file.read(4))[0])  # Each page size: 4 bytes*number of pages

            pages = []
            for ps in page_sizes:
                pages.append(binary_file.read(ps))  # Grab individual pages and each page will contain >= one cookie

            for page in pages:
                page = BytesIO(page)  # Converts the string to a file. So that we can use read/write operations easily.
                page.read(4)  # page header: 4 bytes: Always 00000100
                num_cookies = unpack('<i', page.read(4))[0]  # Number of cookies in each page, first 4 bytes after the page header in every page.

                cookie_offsets = []
                for nc in range(num_cookies):
                    cookie_offsets.append(unpack('<i', page.read(4))[0])  # Every page contains >= one cookie. Fetch cookie starting point from page starting byte

                page.read(4)  # end of page header: Always 00000000

                cookie = ''
                for offset in cookie_offsets:
                    result = {k: '' for k in output_fields}
                    page.seek(offset)  # Move the page pointer to the cookie starting point
                    cookiesize = unpack('<i', page.read(4))[0]  # fetch cookie size
                    cookie = BytesIO(page.read(cookiesize))  # read the complete cookie

                    cookie.read(4)  # unknown

                    flags = unpack('<i', cookie.read(4))[0]  # Cookie flags:  1=secure, 4=httponly, 5=secure+httponly
                    result["flag"] = flag_names.get(flags, 'Unknown')

                    cookie.read(4)  # unknown

                    offsets = [''] * 4  # "Domain", "Name", "Path", "Value"
                    for i in range(4):
                        offsets[i] = unpack('<i', cookie.read(4))[0]  # cookie offset from cookie starting point

                    cookie.read(8)  # end of cookie

                    expiry_date_epoch = unpack('<d', cookie.read(8))[0] + 978307200  # Expiry date is in Mac epoch format: Starts from 1/Jan/2001
                    result["expires"] = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime(expiry_date_epoch))[:-1]  # 978307200 is unix epoch of  1/Jan/2001 //[:-1] strips the last space

                    create_date_epoch = unpack('<d', cookie.read(8))[0] + 978307200  # Cookies creation time
                    result["creation"] = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime(create_date_epoch))[:-1]

                    for j, kind in enumerate(["Domain", "Name", "Path", "Value"]):
                        cookie.seek(offsets[j] - 4)  # fetch domain value from (kind) offset
                        kind_aux = ''
                        k = cookie.read(1)
                        while unpack('<b', k)[0] != 0:
                            kind_aux += k.decode()
                            k = cookie.read(1)

                        result[transform[kind]] = kind_aux

                    yield result
