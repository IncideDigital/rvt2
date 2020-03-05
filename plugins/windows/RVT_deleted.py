
import subprocess
import os
import numpy as np
import pandas as pd
import datetime
from functools import partial

import base.job
from base.utils import check_directory, check_file
from plugins.common.RVT_disk import getSourceImage


def shell_command(cmd, encoding='utf-8'):
    """ Generator of shell command results. """
    with subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE) as proc:
        for line in proc.stdout:
            line = line.strip().decode(encoding)
            yield line


class DeletedStats(base.job.BaseModule):

    # Extensions associated with different kind of files
    _extension_types = {
        'Office': ["pdf", "doc", "docx", "txt", "pdf", "xls", "xlsx", "ppt", "pptx", "odt", "ods"],
        'System': ["exe", "dll", "sys", "mui", "bin", "evt", "evtx", "cab", "com", "drv", "InstallLog", "inf", "uninstall", "bkf", "cat", "grp", "ini", "msi"],
        'Images': ['jpeg', 'jpg', 'bmp', 'gif', 'png'],
        'TempFiles': ['tmp']
    }

    def run(self, path=""):
        self.disk = getSourceImage(self.myconfig)
        if not self.disk.exists():
            self.logger().error(self.disk)
            return

        self.source = self.myconfig('source')
        self.outFolder = self.myconfig('deleteddir')
        check_directory(self.outFolder, create=True)

        # Set maximal dates for later update
        self.firstDate = datetime.date.today() + datetime.timedelta(days=365)
        self.lastDate = datetime.date(1970, 1, 1)

        # Process Timeline deleted files
        self.timelineBodyFile = os.path.join(self.myconfig('timelinesdir'), '{}_BODY.csv'.format(self.source))
        check_file(self.timelineBodyFile, error_missing=True)
        # cmd = r"grep '(deleted' {} | grep -v FILE_NAME | cut -d'|' -f2 | sed 's_^[0-9-][0-9-]*/mnt/\(.*\) (deleted.*$_\1_' | sort -u".format(self.timelineBodyFile)
        cmd = r"grep '(deleted' {} | grep -v '\$FILE_NAME' | cut -d'|' -f2,3,7".format(self.timelineBodyFile)
        deletedTimelineFiles = shell_command(cmd)
        df_timeline = self.get_dataframe(deletedTimelineFiles, 'timeline')

        # Process Recycle
        self.recycleFile = os.path.join(self.myconfig('recycledir'), 'recycle_bin.csv')
        check_file(self.recycleFile, error_missing=True)
        df_recycle = self.get_dataframe(self.recycleFile, 'recycle')

        # Process UsnJrnl and INDX
        df_usnjrnl = pd.DataFrame()
        df_indx = pd.DataFrame()
        for p in self.disk.partitions:
            self.partName = ''.join(['p', p.partition])
            if p.isMountable:

                self.usnJrnlFile = os.path.join(self.myconfig('journaldir'), 'UsnJrnl_{}.csv'.format(p.partition))
                check_file(self.usnJrnlFile, error_missing=True)
                df_u = self.get_dataframe(shell_command(r"grep 'DELETE CLOSE' {} | cut -d',' -f 1,2,4".format(self.usnJrnlFile)), 'usnjrnl')

                self.indxFile = os.path.join(self.myconfig('timelinesdir'), '{}_INDX_timeline.csv'.format(p.partition))
                if not check_file(self.indxFile):
                    df_i = pd.DataFrame()
                # cmd = "grep -v 'SHORT FILENAME FORMAT' {} | grep -v 'NOT OBTAINED' | grep -v 'invalid MFTReference' | cut -d ';' -f 3,4,5,7".format(self.indxFile)   # real
                # cmd = r"tail -n +2 {} | grep -va 'SHORT FILENAME FORMAT' | grep -va 'NOT OBTAINED' | grep -va 'invalid MFTReference' | cut -d ';' -f 2,5,9,14 ".format(self.indxFile)  # unsorted
                # cmd = r"tail -n +2 {} | grep -va 'SHORT FILENAME FORMAT' | grep -va 'NOT OBTAINED' | cut -d ';' -f 2,5,9,14 ".format(self.indxFile)  # unsorted
                cmd = r"tail -n +2 {} | grep -va 'SHORT FILENAME FORMAT' | grep -va 'NOT OBTAINED' | cut -d ';' -f 3,4,6,7,9 ".format(self.indxFile)  # real
                df_i = self.get_dataframe(shell_command(cmd), 'indx')

                df_usnjrnl = self.join_dataframes(df_usnjrnl, df_u)
                df_indx = self.join_dataframes(df_indx, df_i)

        # TODO: timeline_all does not need columns source or reliable
        # Compare Timeline against INDX to extract unique (assuming deleted) files in INDX
        cmd = r"cut -d'|' -f2 {} | grep -v '\$FILE_NAME'".format(self.timelineBodyFile)
        df_all_timeline = self.get_dataframe(shell_command(cmd), 'timeline_all')
        self.logger().debug('Obtaining unique files in INDX')
        df_indx = self.get_deleted_in_INDX(df_all_timeline, df_indx)

        # Create a global dataframe with all artifacts
        self.logger().info('Combining artifacts to create a full list of deleted files')
        df_global = self.combine_artifacts([df_usnjrnl, df_recycle, df_timeline, df_indx])
        print(df_global.shape, df_global.columns)
        duplicated_bin = df_global.duplicated('Filename', keep='first')  # First sources have precedence
        self.logger().info('Found {} duplicated files merging sources'.format(duplicated_bin.sum()))
        print('before dropping', df_global.shape)
        df_global = df_global[~duplicated_bin]
        # df_global.drop_duplicates('Filename', keep='first', inplace=True)
        print('after dropping', df_global.shape)
        print(df_global.columns)
        print(df_global.head())

        # Save global DataFrame
        # outfile = os.path.join(self.outFolder, '{}_deleted.csv'.format(self.source))
        outfile = '/home/pgarcia/global_deleted.csv'
        with open(outfile, 'w') as f:
            f.write(df_global.to_csv(index=False))

        # exit()
        # Create number of files summary based on day, hour and partition
        self.get_stats(self.join_dataframes(df_usnjrnl, df_recycle), 'all')

    def load_data(self, file, artifact=None):
        """ Creates a DataFrame from input data. 'file' may be an url string or a generator. """

        options_csv = {
            'recycle': {'header': 0, 'index_col': 0, 'sep': ';'},
            'usnjrnl': {'header': None, 'skiprows': 1, 'index_col': 0, 'sep': ',', 'names': ['Date', 'Inode', 'Parent_MFT_entry', 'Filename', 'Fileattr', 'Reason']},
            'timeline': {'header': None, 'index_col': None, 'sep': '|', 'names': ['md5', 'Filename', 'Inode', 'Mode', 'UID', 'GID', 'Size', 'Access', 'Modified', 'Changerecord', 'Birth']},
            'indx': {'header': 0, 'index_col': False, 'sep': ';'},
            'timeline_all': {}
        }
        options_df = {
            'recycle': {},
            'usnjrnl': {'columns': ['Date', 'Inode', 'Filename'], 'sep': ',', 'date': True},
            'timeline': {'columns': ['Filename', 'Inode', 'Size'], 'sep': '|', 'date': False},
            'indxgood': {'columns': ['Filename', 'Inode', 'Slack', 'Annotation', 'Size'], 'sep': ';', 'date': False},
            'indx': {'columns': ['Size', 'Slack', 'Filename', 'Annotation'], 'sep': ';', 'date': False},
            'timeline_all': {'columns': ['Filename'], 'sep': '|', 'date': False},
        }

        self.logger().info("Parsing artifact {}{}".format(artifact, ' for partition {}'.format(self.partName) if artifact in ['usnjrnl', 'indx'] else ''))

        try:  # file is a file_object
            df = pd.read_csv(file, **options_csv[artifact], parse_dates=True, infer_datetime_format=True)
        except ValueError:  # file is a generator of rows
            df = pd.DataFrame((line.split(options_df[artifact]['sep']) for line in file), columns=options_df[artifact]['columns'])
            if options_df[artifact]['date']:
                df.index = pd.to_datetime(df.Date, errors='coerce', infer_datetime_format=True)
                df.index = df.index.tz_localize(None)  # TODO: which artifact is UTC ?
                df.drop(columns='Date', inplace=True)
            # df = pd.read_csv(StringIO("\n".join(file)), **options_csv[artifact], parse_dates=True, infer_datetime_format=True)
        except Exception as e:
            self.logger().error('{}:{}'.format(type(e), e))

        self.logger().debug('Data loaded from artifact: {}'.format(artifact))
        # print(df.head())
        return df

    def set_filename(self, df, artifact):
        if artifact == 'recycle':
            df['Filename'] = df.apply(lambda row: '/'.join([row['File'][:3], row['OriginalName'][3:]]), axis=1)
            df.drop(columns=['File', 'OriginalName'], inplace=True)
        elif artifact == 'usnjrnl':
            df['Filename'] = df['Filename'].apply(lambda x: ''.join([self.partName, x.replace('*/', '')]))
        elif artifact in ['timeline', 'timeline_all']:
            df['Filename'] = df['Filename'].apply(lambda x: x[16:])
            df['Filename'] = df['Filename'].apply(self.filter_deleted_ending)
        elif artifact == 'indx':
            df.dropna(subset=['Filename'], inplace=True)  # Some entries are invalid
            df['Filename'] = df['Filename'].apply(lambda x: '/'.join([self.partName, x]))
        return df

    def get_dataframe(self, file, artifact=None):
        """ Return a df from a file with usefull columns added depending on the artifact. """
        df = self.load_data(file, artifact)
        self.logger().debug('Shape before: {}'.format(df.shape))

        if artifact == 'timeline_all':
            self.set_filename(df, artifact)
            return df

        # if artifact in ['recycle', 'usnjrnl']:
        if artifact == 'recycle':
            df['Inode'] = '0'  # there's no inode in the output of recycle
            df['Reliable'] = 1
        elif artifact == 'usnjrnl':
            df['Size'] = -1
            df['Reliable'] = df['Filename'].apply(lambda x: x.find(r'*') < 0).astype(int)
        elif artifact == 'timeline':
            # df['Reliable'] = 1
            df['Reliable'] = df['Filename'].apply(lambda x: x[:-9].find(r'realloc)') < 0).astype(int)  # Slow
            # df = self.treat_FILE_NAME(df)
        elif artifact == 'indx':
            # print(df.shape, df[df['Filename'].isnull()])
            df['Reliable'] = df['Annotation'] != 'unreliable'
            # print(df.Reliable.sum())
            # df['Inode'] = 'not yet'

        self.set_filename(df, artifact)

        # TODO: explore more sofisticated ways to discern which duplicate to keep
        df.drop_duplicates('Filename', keep='last', inplace=True)

        df['Source'] = artifact

        if artifact in ['recycle', 'timeline']:
            df['Partition'] = df['Filename'].apply(lambda x: x[:3])
        else:
            df['Partition'] = self.partName

        self.logger().debug('Shape after: {}'.format(df.shape))
        # print(df[df.Filename == 'p04/Repositorio/fwk/branches/xf-3.4.9.invalid/xf-3.4.6/xf/xf-boot/pom.xml'])

        print(df.columns)
        return df

    def join_dataframes(self, df, new_df):
        # res = pd.concat({grp: subdf for groupObj in stats for grp, subdf in groupObj})
        if df.empty:
            return new_df
        else:
            return pd.concat([df, new_df], sort=False)

    def combine_artifacts(self, dfs):
        # Common fields for global df (no index):
        # Inode is not in recycle (yet)
        # Size is not in UsnJrnl
        # Date not in Timeline or INDX
        fields = ['Filename', 'Date', 'Inode', 'Size', 'Reliable', 'Source']
        for df in dfs:
            print('cols:', df.columns)
            print('shape:', df.shape)
            if df.Source.iloc[0] in ['recycle', 'usnjrnl']:
                df.reset_index(level=0, inplace=True)
            else:
                # TODO: decide which date to choose when it is unclear. Last of macb?
                # df['Date'] = pd.to_datetime('1/1/1970')
                df['Date'] = ''
        return pd.concat([df[fields] for df in dfs], sort=False)

    def get_deleted_in_INDX(self, df_all_timeline, df_indx, save=False):
        """ Select files in INDX not in Timeline. """
        merged = df_all_timeline.merge(df_indx, on='Filename', indicator=True, how='right')
        only_indx = merged[merged['_merge'] == 'right_only']  # Select rows coming only from INDX
        only_indx = only_indx[['Filename', 'Inode', 'Size', 'Reliable', 'Source', 'Partition']]
        print(only_indx.shape, df_all_timeline.shape, df_indx.shape)
        print(only_indx.head())
        print(only_indx.columns)

        if save:
            # outfile = os.path.join(self.outFolder, 'INDX_exclusive.csv'.format(self.source))
            outfile = '/home/pgarcia/only_indx.csv'
            with open(outfile, 'w') as f:
                f.write(only_indx.to_csv(index=False))

        return only_indx

    def get_stats(self, df, artifact=None):
        df = self.add_file_type_cols(df)
        df = self.add_time_cols(df)
        df['Users'] = df['Filename'].apply(lambda x: x.find(r'/Users/') > -1).astype(int)

        cols = ['Filename', 'Day', 'Hour', 'Office', 'System', 'Images', 'TempFiles', 'Users', 'Partition']
        df = df[cols]
        columns_agg_func = {'Filename': 'size', 'Office': np.sum, 'System': np.count_nonzero,
                            'Images': np.sum, 'TempFiles': np.sum, 'Users': 'size'}  # 'Inode': 'size'

        pd.options.display.float_format = '{:,.0f}'.format  # Show floats without decimal (np.sum return float always, not int)

        # print(df[['Partition', 'System', 'Office']], df.dtypes)
        cols = ['Filename', 'Office', 'System', 'Images', 'TempFiles', 'Users', 'Partition', 'Day', 'Hour']
        # Stats by day, partition
        df_sum = df[cols[:-1]].groupby(['Day', 'Partition'], as_index=False).agg(columns_agg_func, fill_value=0)
        df_sum['Hour'] = 'All'
        # Stats by day, hour, partition
        df_items = df[cols].groupby(['Day', 'Hour', 'Partition'], as_index=False).agg(columns_agg_func, fill_value=0)
        # Stats by partition
        total = df[cols[:-2]].groupby('Partition', as_index=False).agg(columns_agg_func)
        total['Day'] = 'All days'
        total['Hour'] = 'All'
        # Summary stats
        data = df_sum.append(df_items, sort=False).append(total, sort=False)
        data = data.set_index(['Day', 'Hour', 'Partition']).sort_index().unstack().fillna(0).replace('False', 0)

        # Create HTML table file with stats.
        outFiles = {'recycle': 'nrecycle_stats.html', 'usnjrnl': 'nusnjrnl_stats.html', 'all': 'deleted_stats.html'}
        # outHtmlFile = os.path.join(self.outFolder, outFiles[artifact])
        outHtmlFile = os.path.join('/home/pgarcia', outFiles[artifact])
        self.save_html_table(data, outfile=outHtmlFile)

        # pt = pd.pivot_table(df2,
        #     values=['Filename', 'Office', 'System', 'Images', 'TempFiles', 'Users'], aggfunc=columns_agg_func,
        #     index=['Day', 'Hour'], columns=['Partition'], fill_value=0, margins=True)

    def add_time_cols(self, df):
        """ Adds for files with a date reference. """
        # TODO: exclude also dates in future?
        if 'Date' in df.columns:
            df.set_index('Date', inplace=True)
        df = df[(df.index.notnull()) & (df.index.year != 1970)]  # Drop lines with wrong timestamps

        self.get_boundary_dates(df.index)

        df['Day'] = df.index.date
        df['Hour'] = df.index.hour
        return df

    def get_boundary_dates(self, index):
        """ Set initial and last dates in the data. Takes an df 'index' (Timestamp) as input"""
        # TODO: Take errors in consideration
        if index[-1].date() > datetime.date.today() + datetime.timedelta(days=365):
            self.logger().warning("Last date in the future. Returning to plausible range of dates")
            return
        self.firstDate = min(self.firstDate, index[0].date())
        self.lastDate = max(self.lastDate, index[-1].date())
        self.logger().info('Initial date: {}\tEnd Date: {}'.format(
            self.firstDate.strftime('%Y-%m-%d'), self.firstDate.strftime('%Y-%m-%d')))

    def add_file_type_cols(self, df, types=['Office', 'System', 'Images', 'TempFiles']):
        """ Add binary columns to 'df' related to file extensions types. """
        assert set(types).issubset(self._extension_types.keys())
        for t in types:
            df[t] = df['Filename'].apply(partial(self.filter_extension, ext=self._extension_types[t])).astype(int)
        return df

    def add_macb_cols(self, df):
        """ Add binary columns related to each of 'macb' times. Only for 'timeline' files. """
        macb = {'Modification': 'm', 'Access': 'a', 'ChangeMeta': 'c', 'Birth': 'b'}
        assert 'macb' in df.columns
        for t in macb:
            df[t] = df['macb'].apply(partial(self.filter_macb, cat=macb[t])).astype(int)
        return df

    @staticmethod
    def treat_FILE_NAME(df, drop=False):
        df['FILE_NAME'] = df['Filename'].apply(lambda x: x.find(r'($FILE_NAME)') > -1)
        if drop:
            df = df[df['FILE_NAME']].drop('FILE_NAME', axis=1)
        return df

    @staticmethod
    def files_by_day(df, cols=['Filename', 'Day']):
        return df[cols].groupby(['Day'])

    @staticmethod
    def files_by_hour(df, cols=['Filename', 'Day', 'Hour']):
        return df[cols].groupby(['Day', 'Hour'])

    @staticmethod
    def massive_days(df):
        return df[['Filename', 'Day']].groupby(['Day']).count().sort_values('filename', ascending=False).head(10)

    @staticmethod
    def filter_macb(x, cat='m'):
        return cat in x

    @staticmethod
    def filter_deleted_ending(x):
        if x[-1] != ')':
            return x
        if x.endswith('(deleted)'):
            return x[:-10]
        elif x.endswith('-realloc)'):
            return x[:-18]
        return x

    @staticmethod
    def filter_extension(x, ext):
        return x.split(".")[-1].strip().lower() in ext

    @staticmethod
    def save_html_table(df, outfile):
        with open(outfile, 'w') as f:
            f.write(df.to_html())

# --- Not used -------------------------------
    def save_html2(self, groupObj, cols=None, cols_printed=None, outfile='/home/pgarcia/tabletest.html'):
        columns_aggregation = {'Filename': 'size', 'Office': np.sum, 'System': np.sum, 'Images': np.sum, 'TempFiles': np.sum, 'Users': 'size'}

        if not cols:
            cols = list(groupObj.get_group(next(iter(groupObj.indices))).columns)
            if not cols_printed:
                cols_printed = [col for col in cols if col not in ['Day', 'Hour']]
        print(cols)
        columns = {key: columns_aggregation[key] for key in cols if key not in ['Day', 'Hour'] and key != 'Partition'}

        print(columns)
        # data = groupObj[cols_printed].agg(columns)
        data = groupObj.agg(columns)

        # df.append(pd.DataFrame(df.MyColumn.sum(), index = ["Total"], columns=["MyColumn"]))
        with open(outfile, 'w') as f:
            f.write(data.to_html())

    def groupCols(self, groupObj):
        for grp, subdf in groupObj:
            print('{}: {} files'.format(grp, subdf.size))
            print(*subdf.values, sep='\n')
        # return pd.concat({grp: subdf for grp, subdf in groupObj})
