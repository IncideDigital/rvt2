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
import sqlite3
import csv
import biplist
import base.job
import base.utils


class Characterization(base.job.BaseModule):
    """
    A module that parses the Manifest.plist to characterize the iPhone.

    The path is an unbacked iPhone backup. See job plugins.ios.unback.Unback

    Configuration:
        - **outfile**: Characterization is writen to this file.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('outfile', os.path.join(self.myconfig('analysisdir'), 'characterize.csv'))

    def run(self, path):
        """
        Parameters:
            path (str): The path to the directory where the backup was unbacked.

        Returns:
            An array of a dictionary with the extracted documentation
        """
        self.logger().debug('Parsing: %s', path)
        self.check_params(path, check_path=True, check_path_exists=True)

        if not base.utils.check_file(os.path.join(path, 'Manifest.plist')):
            raise base.job.RVTError('Manifest.plist not found. Is the source a (decrypted) iOS backup?')

        data = dict()
        manifest = biplist.readPlist(os.path.join(path, 'Manifest.plist'))
        data['Version'] = manifest.get('Version', 'None')
        data['IsEncrypted'] = manifest.get('IsEncrypted', 'None')
        data['LastBackupDate'] = manifest.get('Date', 'None')
        if 'Lockdown' in manifest:
            data['DeviceName'] = manifest['Lockdown'].get('DeviceName', 'None')
            data['UniqueDeviceID'] = manifest['Lockdown'].get('UniqueDeviceID', 'None')
            data['SerialNumber'] = manifest['Lockdown'].get('SerialNumber', 'None')
            data['ProductVersion'] = manifest['Lockdown'].get('ProductVersion', 'None')
            data['ProductType'] = manifest['Lockdown'].get('ProductType', 'None')
            data['BuildVersion'] = manifest['Lockdown'].get('BuildVersion', 'None')
        data['WasPasscodeSet'] = manifest.get('WasPasscodeSet', 'None')

        info = biplist.readPlist(os.path.join(path, 'Info.plist'))
        data['GUID'] = info.get('GUID', 'None')
        data['ICCID'] = info.get('ICCID', 'None')
        data['PhoneNumber'] = info.get('Phone Number', 'None')
        data['MEID'] = info.get('MEID', 'None')
        # check some data, they must be the same
        if 'Lockdown' in manifest:
            assert data['UniqueDeviceID'] == info['Target Identifier']
            assert data['UniqueDeviceID'] == info['Target Identifier'].lower()
            assert data['DeviceName'] == info['Device Name']
            assert data['DeviceName'] == info['Display Name']
            assert data['ProductVersion'] == info['Product Version']
            assert data['BuildVersion'] == info['Build Version']

        status = biplist.readPlist(os.path.join(path, 'Status.plist'))
        data['UUID'] = status['UUID']

        conn = sqlite3.connect('file://{}/HomeDomain/Library/Accounts/Accounts3.sqlite?mode=ro'.format(path), uri=True)
        c = conn.cursor()
        for row in c.execute('SELECT * FROM ZACCOUNT'):
            if row[7] is not None:
                switcher = {
                    33: "iCloud Account",
                    27: "Hotmail Account",
                    38: "Jabber Account",
                    16: "Gmail Account",
                    13: "Yahoo Account",
                    11: "Facebook Account",
                    10: "LinkedIn Account",
                    4: "Twitter Account",
                    8: "Flickr Account",
                }
                tmp = switcher.get(row[7], "nothing")
                if tmp != "nothing":
                    data[tmp] = row[16]

        base.utils.check_file(self.myconfig('outfile'), delete_exists=True, create_parent=True)
        with open(self.myconfig('outfile'), "w") as outfile:
            writer = csv.writer(outfile)
            writer.writerow(("Characteristic", "Value"))
            for k, v in data.items():
                writer.writerow([k, v])

        self.logger().info("iPhone's characterization exported at %s", self.myconfig('outfile'))

        return [data]
