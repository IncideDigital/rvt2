#!/usr/bin/python3
# https://github.com/mac4n6/APOLLO.git
# Copy this script to the root of the apollo project and run.
# Copy the output to directory RVTHOME/conf/ios/apollo

import os
import sys
from configparser import RawConfigParser

RVT2_SECTION = 'ApolloProject.FileParser'
RVT2_OUTPUT = '${{ios.common:iosdir}}/apollo/{}.csv'

# if the script is run with a paramter, use it as the version to get
if(len(sys.argv) > 1):
    VERSION = sys.argv[1]
else:
    VERSION = '12'

rvt2 = RawConfigParser()
modules_rvt2 = []

for f in os.listdir('modules'):
    if f.endswith('txt'):
        module = RawConfigParser(strict=False)  # some files in the apollo project have repeated sections
        module.read('modules/{}'.format(f))

        # get the section name for version 12
        secname = None
        for section in module.sections():
            if 'SQL Query' in section and VERSION in section:
                secname = section
        if secname is None:
            print('Module {}: no section found for version {}'.format(f, VERSION))
        else:
            # name = module.get('Query Metadata', 'QUERY_NAME')
            name = os.path.splitext(f)[0]

            # remember: $ character must be escaped as $$
            regex_rvt2 = '|'.join(list(map(lambda d: '(.*/{}$$)'.format(d), module.get('Database Metadata', 'DATABASE').split(','))))
            secname_rvt2 = 'FileParser.ios.{}'.format(name)

            rvt2.add_section(secname_rvt2)
            rvt2.set(secname_rvt2, 'modules', '\nbase.output.CSVSink file_exists=OVERWRITE outfile="{}"\nbase.input.SQLiteReader'.format(RVT2_OUTPUT.format(name)))
            rvt2.set(secname_rvt2, 'author', module.get('Module Metadata', 'AUTHOR'))
            rvt2.set(secname_rvt2, 'notes', module.get('Module Metadata', 'MODULE_NOTES'))
            query = module.get(secname, 'QUERY')
            if name == 'call_history':
                # call_history module: ZADDRESS is a BLOB, but it must be managed as TEXT
                query = query.replace('ZADDRESS AS "ADDRESS"', 'CAST(ZADDRESS AS TEXT) AS "ADDRESS"')
            # change $ to $$ to prevent interpolation
            rvt2.set(secname_rvt2, 'query', query.replace('$', '$$'))

            modules_rvt2.append('{} {}'.format(regex_rvt2, secname_rvt2))

rvt2.add_section(RVT2_SECTION)
rvt2.set(RVT2_SECTION, 'inherits', 'base.directory.FileParser')
rvt2.set(RVT2_SECTION, 'parsers', '\n'.join(modules_rvt2))

with open('rvt2-ios-{}.ini'.format(VERSION), 'w') as configfile:
    configfile.write("""; AUTOMATICALLY GENERATED FROM THE APOLLO PROJECT USING apollo2rvt2.py
; https://github.com/mac4n6/APOLLO.git

""")
    rvt2.write(configfile)
