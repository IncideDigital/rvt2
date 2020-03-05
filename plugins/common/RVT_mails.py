#!/usr/bin/env python3

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

import datetime
import dateutil.parser
import re
import ast
from collections import Counter, defaultdict, OrderedDict

import base.job
import base.utils


class CharacterizeMails(base.job.BaseModule):

    def run(self, path=''):
        """ Characterize mailbox. Writes a summary file.

        Parameters:
            path (str): path to mailbox.csv

        Configuration:
            - **outdir** (str): Output directory
            - **summary_file** (str): path to output summary_file
            - **n** (int or str): number of most common instances to show for each category
        Yields:
            Dictionaries of individual mail accounts information, such as number of appearences or time ranges
        """

        # Check existance of input file and output txt file
        base.utils.check_file(path, error_missing=True)
        out_summary = self.myconfig('summary_file')
        base.utils.check_file(out_summary, create_parent=True)

        self.n = int(self.myconfig('n'))
        assert self.n > 0

        self.logger().info("Creating mail counts for source {}".format(self.myconfig('source')))
        for r in self.process_mails(path):
            yield r

        self.logger().info("Creating summary mail report for source {}".format(self.myconfig('source')))
        self.summary(out_summary, self.n)

    def process_mails(self, infile):
        """ Main function to extract general statistics from all mails in a mailbox """

        # mailbox.csv headers:
        # client_submit_time;delivery_time;creation_time;modification_time;message;subject;flags;guid;send_or_received;from;to;cc;messageid;x_originating_ip
        h = {'client_submit_time': 'Client submit time', 'delivery_time': 'Delivery time', 'creation_time': 'Creation time', 'modification_time': 'Modification time'}

        mails = defaultdict(OrderedDict)  # Dictionary where keys are mail accounts
        self._init_counters()

        # Initialize global time ranges
        self.global_time_range = dict()
        for times in ['Client submit time', 'Delivery time', 'Creation time', 'Modification time']:
            self.global_time_range[times] = [datetime.datetime(2100, 1, 1), datetime.datetime(1970, 1, 1)]

        # Main loop over all mails:
        for row in self.from_module.run(infile):
            # Create new dict entries for mails dict if they don't exist
            for m in row['all_mails']:
                if m not in mails.keys():
                    mails[m] = self.init_dict(m)

            # From to correspondence counter update
            for mf in row['from_mail']:
                for mt in row['to_cc_mails']:
                    self.from_to_counter.update([(mf, mt)])  # '{} to {}'.format(mf, mt)])

            # Update email counters
            self.from_counter.update(row['from_mail'])
            self.to_counter.update(row['to_mails'])
            self.cc_counter.update(row['cc_mails'])

            # Count if the sender is a public server
            if row['from_public']:
                self.public_counter_from.update(row['from_mail'])
                # Add to FROM public only for reciever mails
                for m in row['to_cc_mails']:
                    mails[m]['FROM public'] = mails[m].get('FROM public', 0) + 1

            # Count mails sent to public client servers and to (CC) public client servers
            for m in row['to_public']:
                mails[row['from_mail'][0]]['TO public'] = mails[row['from_mail'][0]].get('TO public', 0) + 1
                self.public_counter_to.update([m])
            for m in row['cc_public']:
                mails[row['from_mail'][0]]['CC public'] = mails[row['from_mail'][0]].get('CC public', 0) + 1
                self.public_counter_cc.update([m])

            # Add count to sender and reciever mails if message has attachments
            if row['has_attatchments']:
                for m in row['all_mails']:
                    mails[m]['Has attachments'] = mails[m].get('Has attachments', 0) + 1

            # Update date ranges (associated with an email account and global)
            for m in row['all_mails']:
                for time in ['client_submit_time', 'delivery_time', 'creation_time', 'modification_time']:
                    try:
                        t = dateutil.parser.parse(row[time])
                        t = t.replace(tzinfo=None)   # All are in UTC
                        mails[m][' '.join([h[time], 'min'])] = min(t, mails[m][' '.join([h[time], 'min'])])
                        mails[m][' '.join([h[time], 'max'])] = max(t, mails[m][' '.join([h[time], 'max'])])
                    except Exception:
                        continue
                    self.global_time_range[h[time]][0] = min(t, self.global_time_range[h[time]][0])
                    self.global_time_range[h[time]][1] = max(t, self.global_time_range[h[time]][1])

        # Cumulative counters
        self.total_counter = self.from_counter + self.to_counter + self.cc_counter
        to_cc_counter = self.to_counter + self.cc_counter

        # Assign Counters to sender mail dict
        for k in self.total_counter:
            mails[k]['TOTAL count'] = self.total_counter[k]
            mails[k]['FROM count'] = self.from_counter[k]
            mails[k]['TO count'] = self.to_counter[k]
            mails[k]['CC count'] = self.cc_counter[k]
            mails[k]['TO or CC count'] = to_cc_counter[k]

        # Dump the dictionary associated to each mail
        for k, i in sorted(mails.items(), key=lambda k_v: k_v[1]['TOTAL count'], reverse=True):
            # Convert datetimes to str
            for time in ['Client submit time max', 'Delivery time max', 'Creation time max', 'Modification time max',
                         'Client submit time min', 'Delivery time min', 'Creation time min', 'Modification time min']:
                if mails[k][time] == datetime.datetime(1970, 1, 1) or mails[k][time] == datetime.datetime(2100, 1, 1):
                    mails[k][time] == ''
                else:
                    mails[k][time] = mails[k][time].strftime('%Y-%m-%d %H:%M:%S')

            # Reorder dict
            new_order = ['Mail', 'TOTAL count', 'FROM count', 'TO count', 'CC count', 'TO or CC count',
                         'TO public', 'CC public', 'FROM public', 'have attachments',
                         'Client submit time min', 'Client submit time max', 'Delivery time min', 'Delivery time max',
                         'Creation time min', 'Creation time max', 'Modification time min', 'Modification time max']
            yield OrderedDict((key, mails[k][key]) for key in new_order)

        self.mails = mails

    def summary(self, out_summary, n=30):
        """ Creates summary file, including most common email accounts and correspondence.

        Parameters:
            out_summary (str): path to output file
            n (int or str): number of most common instances to show for each category
        """

        n = int(self.myconfig('n', n))
        # Write in summary_file
        with open(out_summary, 'w') as outf:
            outf.write('# Mails Summary {}\n\n'.format(self.myconfig('source')))
            outf.write("{} {}\n".format('Total mail directions found:', len(self.mails)))
            # Get dates global range
            outf.write("\n## {}\n\n".format('Global time ranges'))
            time_names = ["Client Submit", "Delivery", "Creation", "Modification"]
            for i, times in enumerate(['Client submit time', 'Delivery time', 'Creation time', 'Modification time']):
                outf.write("{} times between {} and {}\n".format(time_names[i],
                           self.global_time_range[times][0].strftime("%Y-%m-%d"),
                           self.global_time_range[times][1].strftime("%Y-%m-%d")))

            # Write most common mails
            for name, count in zip(['TOTAL', 'FROM', 'TO', 'CC', 'Public FROM', 'Public TO', 'Public CC', 'FROM TO'],
                                   [self.total_counter, self.from_counter, self.to_counter, self.cc_counter,
                                    self.public_counter_from, self.public_counter_to, self.public_counter_cc, self.from_to_counter]):
                outf.write("\n## {}\n\n".format(name))
                [outf.write('{} : {}\n'.format(*m)) for m in count.most_common(n)]

    def _init_counters(self):
        # Initialize counters to calculate the number of ocurrences of each email direction
        self.from_counter = Counter()
        self.to_counter = Counter()
        self.cc_counter = Counter()

        # Public counters sum up the number of mails sent or recieved by accounts associated with public client mail servers
        self.public_counter_from = Counter()
        self.public_counter_to = Counter()
        self.public_counter_cc = Counter()

        # Counter to sum up emails between two particular users
        self.from_to_counter = Counter()

    @staticmethod
    def init_dict(m):
        d = OrderedDict()
        d.setdefault('Mail', m)
        for field in ['TO public', 'CC public', 'FROM public', 'have attachments']:
            d.setdefault(field, 0)
        for times in ['Client submit time', 'Delivery time', 'Creation time', 'Modification time']:
            d.setdefault(' '.join([times, 'min']), datetime.datetime(2100, 1, 1))
            d.setdefault(' '.join([times, 'max']), datetime.datetime(1970, 1, 1))
        return d


class FilterMails(base.job.BaseModule):

    def run(self, path=''):
        """
        Parse some properties and filter a list of emails, yielding only the ones satisfying the specified conditions.
        Filters must be specified in configuration files under the section 'filter_mails'.
        If the section is empty or does not exists, all mails will be returned.

        Each filter must specify a list of field names (variables) to compare against (values) with the comparsion operators (conditions).
        Optionally a function (pre_function) may be specified to apply before the comparsion.
        The key (operator) determines if every item in the list must be linked with an 'and' or 'or' operator.

        Configuration example:
        select recieved mails with delivery_time between '2006-2-6' and '2007-1-2' where the number of recipients is bigger or equal than 5

            [filter_mails]
            filter1: {'operator': 'and',
                'variables': ['send_or_received', 'delivery_time', 'delivery_time'],
                'conditions': ['__eq__', '__ge__', '__le__'],
                'values': ['R', '2006-2-6', '2007-1-2']}
            filter2: {'operator': 'or',
                'pre_function': ['len', 'len'],
                'variables': ['to_mails', 'cc_mails'],
                'conditions': ['__ge__', '__ge__'],
                'values': ['5', '5']}

        """
        # Regex patterns
        # mail_pattern = re.compile(r'<([\w\.-]+@[\w\.-]+)>')
        # mail_pattern = re.compile(r'<([\w\.+=&-]+@[\w\.+=&-]+)>')  # Extended mail pattern to include [+ = &] characters in mails
        mail_pattern = re.compile(r'<([\w\.+&-]+@[\w\.+=&-]+)>')  # Extended mail pattern to include [+ &] characters in mails
        mail_pattern_ldap = re.compile(r'cn=recipients.cn=([^>]+)', re.I)
        client_pattern = re.compile(r'@([\w-]+)\.')
        attach_pattern = re.compile(r'attachments')

        public_clients = ['gmail', 'yahoo', 'hotmail', 'terra', 'telefonica', 'aol', 'zoho', 'outlook']
        china_public = ['qq', '163', '126', 'aliyun', '139', '189', '263', '21', 'china']
        public_clients.extend(china_public)

        # Load filters (from configuration files) to apply to mails before getting statistics.
        filters = []
        if self.config.has_section('filter_mails'):
            filters = [ast.literal_eval(self.config.get('filter_mails', option)) for option in self.config.options('filter_mails') if option.startswith('filter')]

        # Main loop over all mails:
        for row in self.from_module.run(path):
            # Store mail_adresses from fields ['From', 'To', 'CC']. findall returns a list
            for property, cat in zip(['from_mail', 'to_mails', 'cc_mails'], ['from', 'to', 'cc']):
                row[property] = re.findall(mail_pattern, row[cat])
                row[property].extend(re.findall(mail_pattern_ldap, row[cat]))

            # Remove repeated mails in TO and CC:
            if len(row['to_mails']) > 1:
                row['to_mails'] = list(set(row['to_mails']))
            if len(row['cc_mails']) > 1:
                row['cc_mails'] = list(set(row['cc_mails']))

            # Assure every from_mail has a value, even if it does not follow a typical mail adress pattern
            if not row['from_mail']:
                row['from_mail'] = [row['from']] if row['from'] else ['Unknown']
            # If no recipient is found by regex, take full string
            if not row['to_mails']:
                row['to_mails'] = [row['to']] if row['to'] else ['Unknown']

            row['all_mails'] = list(set(row['from_mail']) | set(row['to_mails']) | set(row['cc_mails']))   # Mails included either in FROM, TO or CC
            row['to_cc_mails'] = list(set(row['to_mails']) | set(row['cc_mails']))  # Mails in TO or CC

            # Public client mails:
            for public, prop in zip(['from_public', 'to_public', 'cc_public'], ['from_mail', 'to_mails', 'cc_mails']):
                row[public] = [m for m in row[prop] for hit in re.findall(client_pattern, m) if hit in public_clients]

            row['has_attatchments'] = bool(re.search(attach_pattern, row['flags']))

            # Filtering process following [filter_mails] section in configuration files
            for filter in filters:
                if not self.filter_fields(row, **filter):
                    break
            else:
                yield row

    def filter_fields(self, row, variables, conditions, values, pre_function=None, operator='and'):
        """ Return True if conditions applied to variables pass.

        Parameters:
            - variables (list): variables to compare
            - conditions (list of str): comparsion function. Ex: ['__gt'__, '__eq__']
            - values (list): values to compare against
            - operator (str): 'and' or 'or'
        """

        operator_action = {'and': (False, True, False), 'or': (True, False, True)}
        if pre_function is None:
            pre_function = [''] * len(values)

        for f, var, cond, v in zip(pre_function, variables, conditions, values):
            if var in ['client_submit_time', 'delivery_time', 'creation_time', 'modification_time']:
                is_time = True
                t = dateutil.parser.parse(row[var]).replace(tzinfo=None)
                v = dateutil.parser.parse(v).replace(tzinfo=None)
            else:
                is_time = False
                try:
                    v = int(v)
                except ValueError:
                    pass
            if getattr(eval("{}({})".format(f, repr(t) if is_time else "row['{}']".format(var))), cond)(v) is operator_action[operator][0]:
                break
        else:
            return operator_action[operator][1]
        return operator_action[operator][2]
