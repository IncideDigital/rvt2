#!/usr/bin/env python3

# Quicklook parser
# Author: Mari DeGrazia
# http://az4n6.blogspot.com/
# arizona4n6@gmail.com
#
# This will parse the Mac quicklook database which holds metadata for viewed thumbnails in the Mac Finder
# This includes parsing out the embedded plist file in the version field as well as extracting thumbnails from the thumbnails.data folder
#
# Command line, run quicklook_parser.py with arguments:
#   python quicklook_parser.py -d "com.apple.QuickLook.thumbnailcache" -o "report_folder"
#
# To read all about the QuickLook artifact, read the white paper by Sara Newcomer:
# iacis.org/iis/2014/10_iis_2014_421-430.pdf
#
# SQL query based off of blog post from Dave:
# http://www.easymetadata.com/2015/01/sqlite-analysing-the-quicklook-database-in-macos/
#
# This program requires that the biplist and Pillow be installed
# Easyinstall can be used to install biplist
# sudo pip install biplist
#
#
# This program requires that the Pillow be installed
# Easyinstall can be used to install biplist
#  sudo pip install Pillow
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You can view the GNU General Public License at <http://www.gnu.org/licenses/>

import os
import argparse
import sqlite3 as lite
import datetime
import os
import tempfile
import shutil
import sys
import subprocess

try:
    from biplist import *
except:
    print("This script requires that the biplist library be installed")
    print("Try sudo pip install biplist")
    exit()

try:
    from PIL import Image
except:
    print("This script requires that the Pil Image library be installed")
    print("Try sudo pip install Pillow")
    exit()

# convert mac absolute time (seconds from 1/1/2001) to human readable


def convert_absolute(mac_absolute_time):
    try:
        bmd = datetime.datetime(2001, 1, 1, 0, 0, 0)
        humantime = bmd + datetime.timedelta(0, mac_absolute_time)
    except:
        return("Error on conversion")
    return(humantime)


def get_parser():
    parser = argparse.ArgumentParser(description='This will parse the quicklook index.sqlite db. Run without options to start GUI')
    parser.add_argument('-d', '--thumbcache_dir', dest="thumbcache_dir", help="com.apple.QuickLook.thumbnailcache folder")
    parser.add_argument('-o', '--output_folder', dest="output_folder", help="Full path to empty folder to hold report and thumbnails")

    return parser


# run command line interface
def command_line(args):

    if args.output_folder is None:
        print("-o OUTPUT_FOLDER argument required")
        exit()
    if args.thumbcache_dir is None:
        print(" -d THUMBCACHE_DIR argument required")
        exit()

    error = verify_files(args.thumbcache_dir)
    if error is not True:
        print(error)
        exit()

    stats = process_database(args.thumbcache_dir, args.output_folder)
    if stats[0] == "Error":
        print(stats[1])
        exit()

    print("Processing Complete\nRecords in table: " + str(stats[0]) + "\n" + "Thumbnails available: " + str(stats[1]) + "\nThumbnails extracted: " + str(stats[2]))


def verify_files(thumbcache_dir):

    # check to see if it is a valid database file
    index = os.path.join(thumbcache_dir, "index.sqlite")
    thumbnails = os.path.join(thumbcache_dir, "thumbnails.data")

    if not os.path.exists(index):
        error = "Could not locate the index.sqlite file in the folder " + thumbcache_dir
        return error

    if not os.path.exists(thumbnails):
        error = "Could not locate the thumbnails.data file in the folder " + thumbcache_dir
        return error
    return True


def process_database(openfolder, savefolder):
    # db = tempfile.mktemp()
    # shutil.copy2(os.path.join(openfolder, "index.sqlite"), db)
    db = os.path.join(openfolder, "index.sqlite")

    thumbnails_data = os.path.join(openfolder, "thumbnails.data")

    try:
        thumbnails_file = open(thumbnails_data, 'rb')
    except:
        error = "Error opening " + thumbnails_data
        return ("Error", error)

    thumbnails_exported = 0

    report = os.path.join(savefolder, "results.csv")
    try:
        report_file = open(report, "w")
    except:
        error = "Error opening report to write to. Verify file is not already open."
        return ("Error", error)

    thumbnails_folder = os.path.join(savefolder, "thumbnails")
    if not os.path.exists(thumbnails_folder):
        os.makedirs(thumbnails_folder)

    error_log = os.path.join(savefolder, "error.log")
    try:
        el = open(error_log, 'w')
    except:
        error = "Error opening log file to write to. Verify file is not already open."
        return ("Error", error)

    con = lite.connect('file://{}?mode=ro'.format(db), uri=True)
    # con = lite.connect(db)

    # get number of thumbnails:
    with con:
        cur = con.cursor()
        sql = "SELECT rowid from thumbnails"
        cur.execute(sql)
        try:
            cur.execute(sql)
        except:
            error = "Error executing SQL. May not be a valid sqlite database, or may not contain the proper fields.\nError may also occur with older versions of sqlite.dll on Windows. Update instructions here: https://deshmukhsuraj.wordpress.com/2015/02/07/windows-python-users-update-your-sqlite3/ "
            return("Error", error)

    rows = cur.fetchall()
    total_thumbnails = len(rows)

    with con:
        cur = con.cursor()

        # SQL syntax taken/modified from #http://www.easymetadata.com/2015/01/sqlite-analysing-the-quicklook-database-in-macos/ and modified to show converted timestamp in UTC
        sql = "select distinct f_rowid,k.folder,k.file_name,k.version,t.hit_count,t.last_hit_date, t.bitsperpixel,t.bitmapdata_location,bitmapdata_length,t.width,t.height,datetime(t.last_hit_date + strftime('%s', '2001-01-01 00:00:00'), 'unixepoch') As [decoded-last_hit_date],fs_id from (select rowid as f_rowid,folder,file_name,fs_id,version from files) k left join thumbnails t on t.file_id = k.f_rowid order by t.hit_count DESC"
        cur.execute(sql)
        try:
            cur.execute(sql)
        except:
            error = "Error executing SQL. May not be a valid sqlite database, or may not contain the proper fields.\nError may also occur with older versions of sqlite.dll on Windows. Update instructions here: https://deshmukhsuraj.wordpress.com/2015/02/07/windows-python-users-update-your-sqlite3/ "
            return("Error", error)

        rows = cur.fetchall()
        total_rows = len(rows)

        if rows:

            total_rows = len(rows)

            report_file.write("Last Hit Date (UTC)|Original File Last Modified(UTC)|Filename|Hit Count|Original File Size|Generator|File Row ID|FS ID\n")

            count = 0
            for row in rows:
                rowid = row[0]
                folder = row[1]
                file_name = row[2]
                hit_count = row[4]
                last_hit_date = row[5]
                bitsperpixel = row[6]
                bitmapdata_location = row[7]
                bitmapdata_length = row[8]
                width = row[9]
                height = row[10]
                decoded_last_hit_date = row[11]
                fs_id = row[12]

                count = count + 1
                version_string = ""

                # create a temp file and extract the plist blob out into the temp file
                filename = "temp.plist"
                with open(filename, 'wb') as output_file:
                    output_file.write(row[3])

                # use the plist library to read in the plist file
                plist = readPlist(filename)

                # read in all the key values in the plist file
                for key, value in plist.items():

                    if key == "date":
                        converted_date = convert_absolute(value)
                        version_last_modified_raw = str(value)
                        version_converted_date = str(converted_date)
                        version_string = "Raw date:" + str(value) + ", Converted Date (UTC): " + str(converted_date)
                    else:
                        version_string = version_string + "," + str(key) + ": " + str(value)

                        if "gen" in str(key):
                            version_generator = str(value)
                        if "size" in str(key):
                            version_org_size = str(value)

                # remove temp plist file
                try:
                    os.remove(filename)
                except:
                    error = "Error removing temp file"
                    return("Error", error)

                # run query for thumbnails. loop through and carve thumbnail for each image
                with con:
                    cur = con.cursor()
                    sql = "SELECT file_id,size,width,height,bitspercomponent,bitsperpixel,bytesperrow,bitmapdata_location,bitmapdata_length from thumbnails where file_id = " + str(rowid)
                    cur.execute(sql)
                    try:
                        cur.execute(sql)
                    except:
                        el.write("Error on thumbnails data query for file id " + rowid)

                thumb_rows = cur.fetchall()

                if len(thumb_rows) == 0:
                    has_thumbnail = "FALSE"
                else:
                    count_thumb = 0
                    for thumb in thumb_rows:
                        count_thumb = count_thumb + 1
                        has_thumbnail = "TRUE"

                        try:
                            # now carve out raw bitmap

                            bitspercomponent = thumb[4]
                            bytesperrow = thumb[6]
                            bitmapdata_location = thumb[7]
                            bitmpatdata_length = thumb[8]

                            # compute the width from the bytes per row as sometimes the width stored in database is funky
                            width = bytesperrow / (bitsperpixel / bitspercomponent)

                            x = width
                            y = thumb[3]
                            thumbnails_file.seek(bitmapdata_location)
                            raw_bitmap = thumbnails_file.read(bitmpatdata_length)

                            # copy out file

                            png = os.path.join(thumbnails_folder, str(row[0]) + "." + row[2] + "_" + str(count_thumb) + ".png")
                            if not os.path.exists(png):

                                imgSize = (int(x), int(y))

                                img = Image.frombytes('RGBA', imgSize, raw_bitmap, decoder_name='raw')
                                img.save(png)
                                thumbnails_exported = thumbnails_exported + 1
                        except:
                            el.write("Error with thumbnail for row id " + str(row[0]) + "\n")
                aux = os.path.join(folder, file_name)
                report_file.write("{}|{}|{}|{}|{}|{}|{}|{}\n".format(decoded_last_hit_date, version_converted_date, aux, hit_count, version_org_size, version_generator, rowid, fs_id))

    report_file.close()
    el.close()
    # os.remove(db)

    return(total_rows, total_thumbnails, thumbnails_exported)

if __name__ == "__main__":

    parser = get_parser()
    args = parser.parse_args()

    command_line(args)
