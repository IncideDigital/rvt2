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

"""

import os
from struct import unpack
from io import BytesIO
import datetime
import base.job
import base.utils
import collections


class Cookies(base.job.BaseModule):
    """
    Module to parse and yield cookies at /HomeDomain/Library/Cookies/.

    This module looks for these cookie files:

    - '/HomeDomain/Library/Cookies/Cookies.binarycookies'
    - '/HomeDomain/Library/Cookies/com.apple.appstored.binarycookies'
    """
    def run(self, path):
        """
        Parameters:
            path (str): Path to the unbacked backup.

        Yields:
            ``{"date_creation", "date_expiration", "name", "domain", "value", "cookie_path", "flags"}``
        """
        self.check_params(path, check_path=True, check_path_exists=True)
        self.logger().info('Parsing: %s', path)

        # cookie files according to the possible iOS versions
        possible_cookie_files = [
            os.path.join(path, 'HomeDomain/Library/Cookies/Cookies.binarycookies'),
            os.path.join(path, 'HomeDomain/Library/Cookies/com.apple.appstored.binarycookies')
        ]
        # search for one of the possible cookie files
        for p in possible_cookie_files:
            if base.utils.check_file(p):
                for c in self.parse_cookie_file(p):
                    yield c

    def parse_cookie_file(self, cookie_file):
        binary_file = open(os.path.join(cookie_file), 'rb')
        file_header = binary_file.read(4).decode()                             # File Magic String:cook

        if str(file_header) != 'cook':
            self.logger().warning("%s is not a binary cookie file", cookie_file)

        num_pages = unpack('>i', binary_file.read(4))[0]               # Number of pages in the binary file: 4 bytes

        page_sizes = []
        for np in range(num_pages):
            page_sizes.append(unpack('>i', binary_file.read(4))[0])  # Each page size: 4 bytes*number of pages

        pages = []
        for ps in page_sizes:
            pages.append(binary_file.read(ps))                      # Grab individual pages and each page will contain >= one cookie

        for page in pages:
            page = BytesIO(page)                                     # Converts the string to a file. So that we can use read/write operations easily.
            page.read(4)                                           # page header: 4 bytes: Always 00000100
            num_cookies = unpack('<i', page.read(4))[0]                # Number of cookies in each page, first 4 bytes after the page header in every page.

            cookie_offsets = []
            for nc in range(num_cookies):
                cookie_offsets.append(unpack('<i', page.read(4))[0])  # Every page contains >= one cookie. Fetch cookie starting point from page starting byte

            page.read(4)                                            # end of page header: Always 00000000

            cookie = " "
            for offset in cookie_offsets:
                page.seek(offset)                                   # Move the page pointer to the cookie starting point
                cookiesize = unpack('<i', page.read(4))[0]             # fetch cookie size
                cookie = BytesIO(page.read(cookiesize))              # read the complete cookie

                cookie.read(4)                                      # unknown

                flags = unpack('<i', cookie.read(4))[0]                # Cookie flags:  1=secure, 4=httponly, 5=secure+httponly
                cookie_flags = " "
                if flags == 0:
                    cookie_flags = " "
                elif flags == 1:
                    cookie_flags = 'Secure'
                elif flags == 4:
                    cookie_flags = 'HttpOnly'
                elif flags == 5:
                    cookie_flags = 'Secure; HttpOnly'
                else:
                    cookie_flags = 'Unknown'

                cookie.read(4)                                      # unknown

                domainoffset = unpack('<i', cookie.read(4))[0]            # cookie domain offset from cookie starting point
                nameoffset = unpack('<i', cookie.read(4))[0]           # cookie name offset from cookie starting point
                pathoffset = unpack('<i', cookie.read(4))[0]           # cookie path offset from cookie starting point
                valueoffset = unpack('<i', cookie.read(4))[0]          # cookie value offset from cookie starting point

                cookie.read(8)                          # end of cookie

                date_expiration_epoch = unpack('<d', cookie.read(8))[0] + 978307200          # Expiry date is in Mac epoch format: Starts from 1/Jan/2001
                date_expiration = datetime.datetime.utcfromtimestamp(date_expiration_epoch).strftime("%Y-%m-%dT%H:%M:%SZ")  # 978307200 is unix epoch of  1/Jan/2001 //[:-1] strips the last space

                date_creation_epoch = unpack('<d', cookie.read(8))[0] + 978307200           # Cookies creation time
                date_creation = datetime.datetime.utcfromtimestamp(date_creation_epoch).strftime("%Y-%m-%dT%H:%M:%SZ")

                cookie.seek(domainoffset - 4)                            # fetch domaain value from domain offset
                domain = " "
                u = cookie.read(1)
                while unpack('<b', u)[0] != 0:
                    # print(type(domain), type(u))
                    domain = domain + u.decode()
                    u = cookie.read(1)

                cookie.seek(nameoffset - 4)                           # fetch cookie name from name offset
                name = " "
                n = cookie.read(1)
                while unpack('<b', n)[0] != 0:
                    name = name + n.decode()
                    n = cookie.read(1)

                cookie.seek(pathoffset - 4)                          # fetch cookie path from path offset
                cookie_path = " "
                pa = cookie.read(1)
                while unpack('<b', pa)[0] != 0:
                    cookie_path = cookie_path + pa.decode()
                    pa = cookie.read(1)

                cookie.seek(valueoffset - 4)                         # fetch cookie value from value offset
                value = " "
                va = cookie.read(1)
                while unpack('<b', va)[0] != 0:
                    value = value + va.decode()
                    va = cookie.read(1)

                if isinstance(name, str):
                    name = name.replace("|", "&#124;")
                    name = name.replace("\n", " - ")
                if isinstance(domain, str):
                    domain = domain.replace("|", "&#124;")
                    domain = domain.replace("\n", " - ")
                if isinstance(cookie_path, str):
                    cookie_path = cookie_path.replace("|", "&#124;")
                    cookie_path = cookie_path.replace("\n", " - ")
                if isinstance(cookie_flags, str):
                    cookie_flags = cookie_flags.replace("|", "&#124;")
                    cookie_flags = cookie_flags.replace("\n", " - ")

                yield collections.OrderedDict(
                    date_creation=date_creation,
                    date_expiration=date_expiration,
                    name=name,
                    domain=domain,
                    value=value,
                    path=cookie_path,
                    cookie_flags=cookie_flags
                )
        binary_file.close()
