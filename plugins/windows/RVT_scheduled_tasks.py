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
import re
import datetime
import dateutil.parser
from lxml import etree
from collections import OrderedDict
from tqdm import tqdm

from plugins.external import jobparser
import base.job
from base.utils import check_directory, save_csv, save_json
from plugins.windows.RVT_os_info import CharacterizeWindows


class ScheduledTasks(base.job.BaseModule):
    """ Parses job files and schedlgu.txt. """

    # ScheduledTasks XML format: https://docs.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema
    tasks_fields = [
        # Registration Info
        'Author', 'Date', 'URI', 'Description', 'Source',
        'Version', 'Documentation', 'SecurityDescriptor',
        # Principals   (RequiredPrivileges is a list !!!)
        'UserId', 'GroupId', 'LogonType', 'DisplayName',
        'RunLevel', 'RequiredPrivileges', 'ProcessTokenSidType',
        # Settings
        'AllowStartOnDemand', 'RestartOnFailure', 'Enabled', 'Hidden',
        'AllowHardTerminate', 'MultipleInstancesPolicy', 'Priority',
        'StartWhenAvailable', 'RunOnlyIfNetworkAvailable', 'NetworkProfileName',
        'RunOnlyIfIdle', 'WakeToRun', 'ExecutionTimeLimit',
        'DeleteExpiredTaskAfter', 'UseUnifiedSchedulingEngine',
        'StopIfGoingOnBatteries', 'DisallowStartIfOnBatteries',
        'DisallowStartOnRemoteAppSession',
        'IdleSettings/Duration', 'IdleSettings/WaitTimeout',
        'IdleSettings/StopOnIdleEnd', 'IdleSettings/RestartOnIdle',
        'NetworkSettings/Name', 'NetworkSettings/Id',
        'RestartOnFailure/Interval', 'RestartOnFailure/Interval'
    ]
    triggers_common_fields = [
        'Enabled', 'StartBoundary', 'EndBoundary', 'ExecutionTimeLimit',
        'Repetition/Interval', 'Repetition/Duration', 'Repetition/StopAtDurationEnd'
    ]
    triggers_event_fields = [
        'EventTrigger/Subscription', 'EventTrigger/Delay',
        'EventTrigger/PeriodOfOccurrences', 'EventTrigger/NumberOfOccurrences',
        'EventTrigger/MatchingElement'
    ]
    triggers_other_fields = [
        'BootTrigger/Delay', 'RegistrationTrigger/Delay', 'TimeTrigger/RandomDelay',
        'LogonTrigger/UserId', 'LogonTrigger/Delay',
        'SessionStateChangeTrigger/UserId', 'SessionStateChangeTrigger/Delay',
        'SessionStateChangeTrigger/StateChange'
    ]
    actions_fields = [
        'Exec/Command', 'Exec/Arguments', 'Exec/WorkingDirectory',
        'ComHandler/ClassId', 'ComHandler/Data',
        'ShowMessage/Title', 'ShowMessage/Body',
        'SendEmail/Server', 'SendEmail/Subject', 'SendEmail/to',
        'SendEmail/Cc', 'SendEmail/Bcc', 'SendEmail/ReplyTo',
        'SendEmail/From', 'SendEmail/Body',
        'HeaderField/Name', 'HeaderField/Value'
        # Attachments is a sequence
    ]
    all_tasks_fields = [*tasks_fields, *triggers_common_fields,
                        *triggers_event_fields, *triggers_other_fields, *actions_fields]
    translation = {}

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)
        self.volume_id = self.myconfig('volume_id')
        # Try to guess volume id/partition from path
        if not self.volume_id:
            assumed_location = os.path.join(self.myconfig('casedir'), self.myconfig('source'), 'mnt')
            if path.find(assumed_location) != -1:
                self.volume_id = path[len(assumed_location) + 1:].split('/')[0]

        self.outfolder = self.myconfig('outdir')
        check_directory(self.outfolder, create=True)
        outfile_jobs = os.path.join(self.outfolder, "jobs_files_{}.csv".format(self.volume_id))
        outfile_sched = os.path.join(self.outfolder, 'schedlgu_{}.csv'.format(self.volume_id))
        outfile_tasks_json = os.path.join(self.outfolder, 'tasks_{}.json'.format(self.volume_id))
        outfile_tasks_csv = os.path.join(self.outfolder, 'tasks_{}.csv'.format(self.volume_id))

        self.logger().debug("Parsing artifacts from scheduled tasks files (.job)")
        save_csv(self.parse_Task(path), outfile=outfile_jobs, file_exists='APPEND', quoting=0)

        self.logger().debug("Parsing artifacts from Task Scheduler Service log files (schedlgu.txt)")
        save_csv(self.parse_schedlgu(path), config=self.config,
                 outfile=outfile_sched, file_exists='APPEND', quoting=0)

        self.logger().debug("Parsing XML files from Tasks directory")
        xml_tasks = list(self.parse_task_xml(path))
        save_json(xml_tasks, config=self.config,
                  outfile=outfile_tasks_json, file_exists='APPEND')
        save_csv(self.summarize_xml_tasks(xml_tasks), config=self.config,
                 outfile=outfile_tasks_csv, file_exists='APPEND')

        return []

    def parse_Task(self, directory):
        """ Parse .job files """
        jobs_files = [os.path.join(directory, file) for file in os.listdir(directory) if file.endswith('.job')]

        for file in jobs_files:
            with open(file, "rb") as f:
                data = f.read()
            # Every .job file is a task
            job = jobparser.Job(data)
            yield OrderedDict([("Product Info", jobparser.products.get(job.ProductInfo)),
                               ("File Version", job.FileVersion),
                               ("UUID", job.UUID),
                               ("Maximum Run Time", job.MaxRunTime),
                               ("Exit Code", job.ExitCode),
                               ("Status", jobparser.task_status.get(job.Status, "Unknown Status")),
                               ("Flasgs", job.Flags_verbose),
                               ("Date Run", job.RunDate),
                               ("Running Instances", job.RunningInstanceCount),
                               ("Application", "{} {}".format(job.Name, job.Parameter)),
                               ("Working Directory", job.WorkingDirectory),
                               ("User", job.User),
                               ("Comment", job.Comment),
                               ("Scheduled Date", job.ScheduledDate)])

        self.logger().debug("Finished extraction from scheduled tasks .job")

    def parse_schedlgu(self, directory):
        """ Parse SCHEDLGU.TXT files """
        sched_files = [os.path.join(directory, file) for file in os.listdir(directory) if file.lower().endswith('schedlgu.txt')]

        for file in sched_files:
            with open(file, 'r', encoding='utf16') as sched:
                dates = {'start': datetime.datetime.min, 'end': datetime.datetime.min}
                parsed_entry = False
                for line in sched:
                    if line == '\n':
                        continue
                    elif line.startswith('"'):
                        service = line.rstrip('\n').strip('"')
                        if parsed_entry:
                            yield OrderedDict([('Service', service), ('Started', dates['start']), ('Finished', dates['end'])])
                        parsed_entry = False
                        dates = {'start': datetime.datetime.min, 'end': datetime.datetime.min}
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

        self.logger().debug("Finished extraction from schedlgu.txt")

    def parse_task_xml(self, directory):
        """ Parse UTF-16 encoded XML files inside Tasks folders """
        task_xml_files = []
        for root_folder, subf, files in os.walk(directory):
            for file in files:
                if not file.endswith('.job') and not file.lower().endswith('schedlgu.txt'):
                    task_xml_files.append(os.path.join(root_folder, file))

        os_info = CharacterizeWindows(config=self.config)

        for file in tqdm(task_xml_files, total=len(task_xml_files), desc=self.section):
            res = {}
            # res = {'File': os.path.basename(file)}
            # res = {fld: '' for fld in self.all_tasks_fields}
            try:  # Not all files may be in XML format
                st = etree.parse(file)
            except Exception as exc:
                self.logger().debug('File {} may not be a valid XML: {}'.format(file, exc))
                continue

            # Get the namespace. All tags are preceded by this namespace
            ns = {'ns': st.getroot().nsmap[None]}

            # Fill general fields
            for field in self.tasks_fields:
                xpath_search = "//" + '/'.join(["ns:{}".format(subf) for subf in field.split('/')])
                value = st.xpath(xpath_search, namespaces=ns)
                if value:
                    res[field] = value[0].text
            privileges = [value.text for value in st.xpath('//ns:RequiredPrivileges/ns:Privilege/*', namespaces=ns)]
            if privileges:
                res['RequiredPrivileges'] = ', '.join(privileges)

            # Parse Triggers and Actions fields
            res['Triggers'] = list(self._parse_triggers(st, ns))
            res['Actions'] = list(self._parse_actions(st, ns))

            # Get user name from UserID
            res['User'] = os_info.get_user_name_from_sid(res['UserId'], partition=self.volume_id, sid_default=True)

            yield res

    def summarize_xml_tasks(self, xml_tasks):
        """ Get most relevant fields from task definitions"""
        for t in xml_tasks:
            res = {'StartBoundary': '',
                   'TaskName': t.get('URI', ''),
                   'User': t.get('User', ''),
                   'Command': '',
                   'Arguments': '',
                   'Enabled': t.get('Enabled', ''),
                   'RunLevel': t.get('RunLevel', ''),
                   'Description': t.get('Description', '')
                  }

            # TODO: consider more than one action
            if t.get('Actions', None):
                res['Command'] = t['Actions'][0].get('Exec/Command', '')
                res['Arguments'] = t['Actions'][0].get('Exec/Arguments', '')

            if t.get('Triggers', None):
                for trig in t['Triggers']:
                    if 'StartBoundary' in trig:
                        res['StartBoundary'] = trig['StartBoundary']
                        yield res


    def _parse_triggers(self, tree, ns={'ns': ''}):
        result = {}
        for action in tree.xpath("//ns:Triggers/*", namespaces=ns):
            for field in self.triggers_common_fields:
                xpath_search = "//" + '/'.join(["ns:{}".format(subf) for subf in field.split('/')])
                value = action.xpath(xpath_search, namespaces=ns)
                if value:
                    result[field] = value[0].text
            action_type = action.tag
            if action_type.endswith('CalendarTrigger'):
                result.update(self._parse_calendar(action, ns))
                yield result
            elif action_type.endswith('EventTrigger'):
                for field in self.triggers_event_fields:
                    xpath_search = "//" + '/'.join(["ns:{}".format(subf) for subf in field.split('/')])
                    value = action.xpath(xpath_search, namespaces=ns)
                    if value:
                        result[field] = value[0].text
                value_queries = [value.text for value in action.xpath('//ns:ValueQueries/ns:Value/*', namespaces=ns)]
                result['ValueQueries'] = ', '.join(value_queries)
                yield result
            else:
                for field in self.triggers_other_fields:
                    xpath_search = "//" + '/'.join(["ns:{}".format(subf) for subf in field.split('/')])
                    value = action.xpath(xpath_search, namespaces=ns)
                    if value:
                        result[field] = value[0].text
                yield result

    def _parse_actions(self, tree, ns={'ns': ''}):
        result = {}
        for action in tree.xpath("//ns:Actions/*", namespaces=ns):
            for field in self.actions_fields:
                xpath_search = "//" + '/'.join(["ns:{}".format(subf) for subf in field.split('/')])
                value = action.xpath(xpath_search, namespaces=ns)
                if value:
                    result[field] = value[0].text
            yield result

    def _parse_calendar(self, node, ns={'ns': ''}):
        result = {}
        if node.xpath('//ns:ScheduleByDay', namespaces=ns):
            result['DaysInterval'] = node.xpath('//ns:DaysInterval', namespaces=ns)[0].text
        elif node.xpath('//ns:ScheduleByWeek', namespaces=ns):
            result['WeeksInterval'] = node.xpath('//ns:WeeksInterval', namespaces=ns)[0].text
            days = [day.tag[len(ns['ns']) + 2:] for day in node.xpath('//ns:DaysOfWeek/*', namespaces=ns)]
            result['DaysOfWeek'] = ', '.join(days)
        elif node.xpath('//ns:ScheduleByMonth', namespaces=ns):
            days = [day.text for day in node.xpath('//ns:DaysOfMonth/ns:Day/*', namespaces=ns)]
            months = [month.tag[len(ns['ns']) + 2:] for month in node.xpath('//ns:Months/*', namespaces=ns)]
            result['DaysOfMonth'] = ', '.join(days)
            result['Months'] = ', '.join(months)
        elif node.xpath('//ns:ScheduleByMonthDayOfWeek', namespaces=ns):
            days = [day.tag[len(ns['ns']) + 2:] for day in node.xpath('//ns:DaysOfWeek/*', namespaces=ns)]
            months = [month.tag[len(ns['ns']) + 2:] for month in node.xpath('//ns:Months/*', namespaces=ns)]
            weeks = [week.text for week in node.xpath('//ns:Weeks/*', namespaces=ns)]
            result['DaysOfWeek'] = ', '.join(days)
            result['Months'] = ', '.join(months)
            result['Weeks'] = ', '.join(weeks)
        return result
