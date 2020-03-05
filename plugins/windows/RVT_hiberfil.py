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

import re
import os
import subprocess
from plugins.common.RVT_files import GetFiles
from base.utils import check_folder
import base.job
from base.commands import run_command


class Hiberfil(base.job.BaseModule):

    def run(self, path=""):
        """ Get information of hiberfil.sys

        """
        volatility = self.config.get('plugins.common', 'volatility', '/usr/local/bin/vol.py')

        hiber_path = self.myconfig('outdir')
        check_folder(hiber_path)

        search = GetFiles(self.config, vss=self.myflag("vss"))
        hiberlist = search.search("/hiberfil.sys$")

        for h in hiberlist:
            aux = re.search("{}/([^/]*)/".format(base.utils.relative_path(self.myconfig('mountdir'), self.myconfig('casedir'))), h)
            partition = aux.group(1)

            hiber_raw = os.path.join(hiber_path, "hiberfil_{}.raw".format(partition))
            profile, version = self.get_win_profile(partition)
            with open(os.path.join(hiber_path, "hiberinfo_{}.txt".format(partition)), 'w') as pf:
                pf.write("Profile: %s\nVersion: %s" % (profile, version))
            if version.startswith("5") or version.startswith("6.0") or version.startswith("6.1"):
                self.logger().info("Uncompressing {}".format(h))
                run_command([volatility, "--profile={}".format(profile), "-f", os.path.join(self.myconfig('casedir'), h), "imagecopy", "-O", hiber_raw], logger=self.logger())
            else:
                self.logger().info("{} files could not be descompressed with a linux distro".format(h))
                self.logger().info("Descompress with Windows 8 o higher hiberfil.sys file using https://arsenalrecon.com/weapons/hibernation-recon/")
                self.logger().info("save output at {}".format(hiber_raw))
            self.vol_extract(hiber_raw, profile, version)
        return []

    def vol_extract(self, archive, profile, version):
        """ Extracts data from decompressed hiberfil files

        Args:
            archive (str): file to extract information
            profile (str): volatility profile
            version (str): windows version
        """
        if not os.path.isfile(archive):
            if version.startswith("5") or version.startswith("6.0") or version.startswith("6.1"):
                self.logger().warning("Linux distributions has not programs to decompress hiberfil.sys from Windows version {}".format(version))
                self.logger().warning("You could decompress hiberfil.sys using hibernation-recon from https://arsenalrecon.com in a Win8+ OS")
                self.logger().warning("Save output at {}".format(archive))
                self.logger().Error("Unable to decompress hiberfil.sys")
                exit(1)

        plugins = ["pslist", "netscan", "filescan", "shutdowntime", "mftparser"]
        vol = self.config.get('plugins.common', 'volatility', '/usr/local/bin/vol.py')

        partition = re.search(r"/hiberfil_([vp\d]+)\.raw$", archive)
        partition = partition.group(1)
        hiber_output = os.path.join(self.myconfig('outdir'), "data_{}.txt".format(partition))

        self.logger().info("Extracting information from {}".format(archive.split(self.myconfig('outputdir'))[-1]))

        with open(hiber_output, "w") as f:
            for plugin in plugins:
                self.logger().info("Plugin {}".format(plugin))
                output = subprocess.check_output([vol, "--profile={}".format(profile), "-f", archive, plugin]).decode()
                f.write("*********** {} ************\n{}\n".format(plugin, output))

    def get_win_profile(self, partition):
        """ Gets volatility profile and windows version from reg_Info file

        Args:
            partition (str): partition number to get volatility profile

        returns:
            tuple: tuple of volatility profile and windows version
        """
        profile = {}
        profile["10.0x64"] = "Win10x64"
        profile["10.0.10240x64"] = "Win10x64_10240_17770"
        profile["10.0.10586x64"] = "Win10x64_10586"
        profile["10.0.14393x64"] = "Win10x64_14393"
        profile["10.0.15063x64"] = "Win10x64_15063"
        profile["10.0.16299x64"] = "Win10x64_16299"
        profile["10.0.17134x64"] = "Win10x64_17134"
        profile["10.0.17763x64"] = "Win10x64_17763"
        profile["10.0x86"] = "Win10x86"
        profile["10.0.10240x86"] = "Win10x86_10240_17770"
        profile["10.0.10586x86"] = "Win10x86_10586"
        profile["10.0.14393x86"] = "Win10x86_14393"
        profile["10.0.15063x86"] = "Win10x86_15063"
        profile["10.0.16299x86"] = "Win10x86_16299"
        profile["10.0.17134x86"] = "Win10x86_17134"
        profile["10.0.17763x86"] = "Win10x86_17763"
        profile["6.3.9600x64"] = "Win8SP1x64"
        profile["6.3.9600x64"] = "Win81U1x64"
        profile["6.2.9200x64"] = "Win8SP0x64"
        profile["6.3.9600x86"] = "Win8SP1x86"
        profile["6.3.9600x86"] = "Win81U1x86"
        profile["6.2.9200x86"] = "Win8SP0x86"
        profile["6.1.7601x64"] = "Win7SP1x64"
        profile["6.1.7600x64"] = "Win7SP0x64"
        profile["6.1.7601x86"] = "Win7SP1x86"
        profile["6.1.7600x86"] = "Win7SP0x86"
        profile["6.0.6000x64"] = "VistaSP0x64"
        profile["6.0.6001x64"] = "VistaSP1x64"
        profile["6.0.6002x64"] = "VistaSP2x64"
        profile["6.0.6000x86"] = "VistaSP0x86"
        profile["6.0.6001x86"] = "VistaSP1x86"
        profile["6.0.6002x86"] = "VistaSP2x86"
        profile["5.2.3790x64"] = "Win2003SP2x64"
        profile["5.2.3790x86"] = "Win2003SP2x86"
        profile["5.1.2600x64"] = "WinXPSP3x64"
        profile["5.1.2600x86"] = "WinXPSP3x86"

        srch = re.compile(r"(CurrentVersion|CurrentBuild|BuildLabEx)\s+:\s+(.*)")

        info_file = os.path.join(self.myconfig('hivesdir'), "01_operating_system_information_{}.txt".format(partition))
        if not os.path.isfile(info_file):
            self.logger().warning("Not exists {}".format(info_file))
            return -1

        prof = {}
        with open(info_file, "r") as f:
            for line in f:
                aux = srch.search(line)
                if aux:
                    prof[aux.group(1)] = aux.group(2)

        if prof == {}:
            self.logger().info("Information about Windows version cannot be extracted from {}".format(info_file))
            return -2

        if "amd64" in prof["BuildLabEx"]:
            arquitecture = "x64"
        else:
            arquitecture = "x86"

        prof = "{}.{}{}".format(prof["CurrentVersion"], prof["CurrentBuild"], arquitecture)

        if prof not in profile.keys():
            prof = "{}{}".format(prof["CurrentVersion"], arquitecture)
        return profile[prof], prof
