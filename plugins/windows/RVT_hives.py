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

import csv
import os
import re
import datetime
import dateutil.parser
from collections import OrderedDict
from Registry import Registry
from Registry.RegistryParse import parse_windows_timestamp as _parse_windows_timestamp

from plugins.external import jobparser
import base.job
from base.utils import check_directory, save_csv
from base.commands import run_command
from plugins.common.RVT_files import GetFiles
from plugins.common.RVT_filesystem import FileSystem


def parse_windows_timestamp(value):
    try:
        return _parse_windows_timestamp(value)
    except ValueError:
        return datetime.datetime.min


WINDOWS_TIMESTAMP_ZERO = parse_windows_timestamp(0).strftime("%Y-%m-%d %H:%M:%S")


class AmCache(base.job.BaseModule):
    """ Parses Amcache.hve registry hive. """

    def run(self, path=""):
        vss = self.myflag('vss')
        self.search = GetFiles(self.config, vss=vss)

        outfolder = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(outfolder, create=True)

        amcache_hives = [path] if path else self.search.search("Amcache.hve$")
        for am_file in amcache_hives:
            self.amcache_path = os.path.join(self.myconfig('casedir'), am_file)
            partition = am_file.split("/")[2]
            self.logger().info("Parsing {}".format(am_file))
            self.outfile = os.path.join(outfolder, "amcache_{}.csv".format(partition))

            try:
                reg = Registry.Registry(os.path.join(self.myconfig('casedir'), am_file))
                entries = self.parse_amcache_entries(reg)
                save_csv(entries, outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
            except KeyError:
                self.logger().warning("Expected subkeys not found in hive file: {}".format(am_file))
            except Exception as exc:
                self.logger().warning("Problems parsing: {}. Error: {}".format(am_file, exc))

        self.logger().info("Amcache.hve parsing finished")
        return []

    def parse_amcache_entries(self, registry):
        """ Return a generator of dictionaries describing each entry in the hive.

        Fields:
            * KeyLastWrite: Possible application first executed time (must be tested)
            * AppPath: application path inside the volume
            * AppName: friendly name for application, if any
            * Sha1Hash: binary file SHA-1 hash value
            * GUID: Volume GUID the application was executed from
        """
        # Hive subkeys may have two different subkeys
        #   * {GUID}\\Root\\File
        #   * {GUID}\\Root\\InventoryApplicationFile
        found_key = ''
        structures = {'File': self._parse_File_entries, 'InventoryApplicationFile': self._parse_IAF_entries}
        for key, func in structures.items():
            try:
                volumes = registry.open("Root\\{}".format(key))
                found_key = key
                self.logger().debug('Parsing entries in key: Root\\{}'.format(key))
                for app in func(volumes):
                    yield app
            except Registry.RegistryKeyNotFoundException:
                self.logger().info('Key "Root\\{}" not found'.format(key))

        if not found_key:
            raise KeyError

    def _parse_File_entries(self, volumes):
        """ Parses File subkey entries for amcache hive """
        fields = {'LastModified': "17", 'AppPath': "15", 'AppName': "0", 'Sha1Hash': "101"}
        for volumekey in volumes.subkeys():
            for filekey in volumekey.subkeys():
                app = OrderedDict([('KeyLastWrite', WINDOWS_TIMESTAMP_ZERO), ('AppPath', ''), ('AppName', ''),
                                   ('Sha1Hash', ''), ('LastModified', WINDOWS_TIMESTAMP_ZERO), ('GUID', '')])
                app['GUID'] = volumekey.path().split('}')[0][1:]
                app['KeyLastWrite'] = filekey.timestamp()
                for f in fields:
                    try:
                        val = filekey.value(fields[f]).value()
                        if f == 'Sha1Hash':
                            val = val[4:]
                        elif f == 'LastModified':
                            val = parse_windows_timestamp(val).strftime("%Y-%m-%d %H:%M:%S")
                        app.update({f: val})
                    except Registry.RegistryValueNotFoundException:
                        pass
                yield app

    def _parse_IAF_entries(self, volumes):
        """ Parses InventoryApplicationFile subkey entries for amcache hive.

        Yields: dict with keys'FirstRun','AppPath') """
        names = {'LowerCaseLongPath': 'AppPath', 'FileId': 'Sha1Hash', 'ProductName': 'AppName'}
        for volumekey in volumes.subkeys():
            app = OrderedDict([('KeyLastWrite', WINDOWS_TIMESTAMP_ZERO), ('AppPath', ''), ('AppName', ''),
                               ('Sha1Hash', ''), ('LastModified', WINDOWS_TIMESTAMP_ZERO), ('GUID', '')])
            app['GUID'] = volumekey.path().split('}')[0][1:]
            app['KeyLastWrite'] = volumekey.timestamp()
            for v in volumekey.values():
                if v.name() in ['LowerCaseLongPath', 'ProductName']:
                    app.update({names.get(v.name(), v.name()): v.value()})
                elif v.name() == 'FileId':
                    sha = v.value()[4:]  # SHA-1 hash is registered 4 0's padded
                    app.update({names.get(v.name(), v.name()): sha})
            yield app


class ShimCache(base.job.BaseModule):
    """ Extracts ShimCache information from registry hives. """

    # TODO: .sdb shim database files (ex: Windows/AppPatch/sysmain.sdb)

    def run(self, path=""):
        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.vss = self.myflag('vss')
        self.logger().info("Parsing ShimCache from registry")

        outfolder = self.myconfig('voutdir') if self.vss else self.myconfig('outdir')
        SYSTEM = list(self.search.search(r"windows/System32/config/SYSTEM$"))
        check_directory(outfolder, create=True)

        partition_list = set()
        for f in SYSTEM:
            aux = re.search(r"([vp\d]*)/windows/System32/config", f, re.I)
            partition_list.add(aux.group(1))

        output_files = {p: os.path.join(outfolder, "shimcache_%s.csv" % p) for p in partition_list}

        for f in SYSTEM:
            save_csv(self.parse_ShimCache_hive(f), outfile=output_files[f.split("/")[2]], file_exists='OVERWRITE', quoting=0)

        self.logger().info("Finished extraction from ShimCache")
        return []

    def parse_ShimCache_hive(self, sysfile):
        """ Launch shimcache regripper plugin and parse results """
        ripcmd = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')
        date_regex = re.compile(r'\w{3}\s\w{3}\s+\d+\s\d{2}:\d{2}:\d{2}\s\d{4} Z')

        res = run_command([ripcmd, "-r", os.path.join(self.myconfig('casedir'), sysfile), "-p", "shimcache"], logger=self.logger())
        for line in res.split('\n'):
            if ':' not in line[:4]:
                continue
            matches = re.search(date_regex, line)
            if matches:
                path = line[:matches.span()[0] - 2]
                date = str(datetime.datetime.strptime(matches.group(), '%a %b %d %H:%M:%S %Y Z'))
                executed = bool(len(line[matches.span()[1]:]))
                yield OrderedDict([('LastModified', date), ('AppPath', path), ('Executed', executed)])


class ScheduledTasks(base.job.BaseModule):
    """ Parses job files and schedlgu.txt. """

    def run(self, path=""):
        self.vss = self.myflag('vss')
        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.outfolder = self.myconfig('voutdir') if self.vss else self.myconfig('outdir')
        check_directory(self.outfolder, create=True)

        self.logger().info("Parsing artifacts from scheduled tasks files (.job)")
        self.parse_Task()
        self.logger().info("Parsing artifacts from Task Scheduler Service log files (schedlgu.txt)")
        self.parse_schedlgu()
        return []

    def parse_Task(self):
        jobs_files = list(self.search.search(r"\.job$"))
        partition_list = set()
        for f in jobs_files:
            partition_list.add(f.split("/")[2])

        f = {}
        csv_files = {}
        writers = {}

        for p in partition_list:
            csv_files[p] = open(os.path.join(self.outfolder, "jobs_files_%s.csv" % p), "w")
            writers[p] = csv.writer(csv_files[p], delimiter=";", quotechar='"')
            writers[p].writerow(["Product Info", "File Version", "UUID", "Maximum Run Time", "Exit Code", "Status", "Flags", "Date Run",
                                 "Running Instances", "Application", "Working Directory", "User", "Comment", "Scheduled Date"])

        for file in jobs_files:
            partition = file.split("/")[2]
            with open(os.path.join(self.myconfig('casedir'), file), "rb") as f:
                data = f.read()
            job = jobparser.Job(data)
            writers[partition].writerow([jobparser.products.get(job.ProductInfo), job.FileVersion, job.UUID, job.MaxRunTime, job.ExitCode, jobparser.task_status.get(job.Status, "Unknown Status"),
                                         job.Flags_verbose, job.RunDate, job.RunningInstanceCount, "{} {}".format(job.Name, job.Parameter), job.WorkingDirectory, job.User, job.Comment, job.ScheduledDate])
        for csv_file in csv_files.values():
            csv_file.close()

        self.logger().info("Finished extraction from scheduled tasks .job")

    def parse_schedlgu(self):
        sched_files = list(self.search.search(r"schedlgu\.txt$"))
        for file in sched_files:
            partition = file.split("/")[2]
            save_csv(self._parse_schedlgu(os.path.join(self.myconfig('casedir'), file)),
                     outfile=os.path.join(self.outfolder, 'schedlgu_{}.csv'.format(partition)), file_exists='OVERWRITE', quoting=0)
        self.logger().info("Finished extraction from schedlgu.txt")

    def _parse_schedlgu(self, file):
        with open(file, 'r', encoding='utf16') as sched:
            dates = {'start': WINDOWS_TIMESTAMP_ZERO, 'end': WINDOWS_TIMESTAMP_ZERO}
            parsed_entry = False
            for line in sched:
                if line == '\n':
                    continue
                elif line.startswith('"'):
                    service = line.rstrip('\n').strip('"')
                    if parsed_entry:
                        yield OrderedDict([('Service', service), ('Started', dates['start']), ('Finished', dates['end'])])
                    parsed_entry = False
                    dates = {'start': WINDOWS_TIMESTAMP_ZERO, 'end': WINDOWS_TIMESTAMP_ZERO}
                    continue
                for state, words in {'start': ['Started', 'Iniciado'], 'end': ['Finished', 'Finalizado']}.items():
                    for word in words:
                        if line.startswith('\t{}'.format(word)):
                            try:
                                dates[state] = dateutil.parser.parse(line[re.search(r'\d', line).span()[0]:].rstrip('\n')).strftime("%Y-%m-%d %H:%M:%S")
                                parsed_entry = True
                            except Exception:
                                pass
                            break


class SysCache(base.job.BaseModule):

    def run(self, path=""):
        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.vss = self.myflag('vss')
        self.logger().info("Parsing Syscache from registry")
        self.parse_SysCache_hive()
        return []

    def parse_SysCache_hive(self):
        outfolder = self.myconfig('voutdir') if self.vss else self.myconfig('outdir')
        # self.tl_file = os.path.join(self.myconfig('timelinesdir'), "%s_BODY.csv" % self.myconfig('source'))
        check_directory(outfolder, create=True)
        SYSC = self.search.search(r"/System Volume Information/SysCache.hve$")

        ripcmd = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')

        for f in SYSC:
            p = f.split('/')[2]
            output_text = run_command([ripcmd, "-r", os.path.join(self.myconfig('casedir'), f), "-p", "syscache_csv"], logger=self.logger())
            output_file = os.path.join(outfolder, "syscache_%s.csv" % p)

            self.path_from_inode = FileSystem(config=self.config).load_path_from_inode(self.myconfig, p, vss=self.vss)

            save_csv(self.parse_syscache_csv(p, output_text), outfile=output_file, file_exists='OVERWRITE')

        self.logger().info("Finished extraction from SysCache")

    def parse_syscache_csv(self, partition, text):
        for line in text.split('\n')[:-1]:
            line = line.split(",")
            fileID = line[1]
            inode = line[1].split('/')[0]
            name = self.path_from_inode.get(inode, [''])[0]
            try:
                yield OrderedDict([("Date", dateutil.parser.parse(line[0]).strftime("%Y-%m-%dT%H:%M%SZ")),
                                   ("Name", name), ("FileID", fileID), ("Sha1", line[2])])
            except Exception:
                yield OrderedDict([("Date", dateutil.parser.parse(line[0]).strftime("%Y-%m-%dT%H:%M%SZ")),
                                   ("Name", name), ("FileID", fileID), ("Sha1", "")])


class TaskFolder(base.job.BaseModule):

    def run(self, path=""):
        """ Prints prefetch info from folder

        """
        print("Product Info|File Version|UUID|Maximum Run Time|Exit Code|Status|Flags|Date Run|Running Instances|Application|Working Directory|User|Comment|Scheduled Date")

        for fichero in os.listdir(path):
            if fichero.endswith(".job"):
                data = ""
                with open(os.path.join(path, fichero), "rb") as f:
                    data = f.read()
                job = jobparser.Job(data)
                print("{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}".format(jobparser.products.get(job.ProductInfo), job.FileVersion, job.UUID, job.MaxRunTime, job.ExitCode, jobparser.task_status.get(job.Status, "Unknown Status"),
                                                                         job.Flags_verbose, job.RunDate, job.RunningInstanceCount, "{} {}".format(job.Name, job.Parameter), job.WorkingDirectory, job.User, job.Comment, job.ScheduledDate))
