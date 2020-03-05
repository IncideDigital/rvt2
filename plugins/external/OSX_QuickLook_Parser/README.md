# OSX-QuickLook-Parser
Parse the Mac Quicklook index.sqlite database

This script will parse the Mac / OSX QuickLook index.sqlite database. This database contains information about thumbnails that have been generated on a Mac. This includes information like the file path to the original file, a hit count, the last date and time the thumbnail was accessed, the original file size and last modified date of the original file.
While an SQL query works for most of the data, there is a "version" field that contains a BLOB. This BLOB conatinas a binary plist file with additional data. This script parses out this BLOB data in addtion to the other fields.

This will also carve out the thumbnails in the thumbnails.data file.

Required libraries for the python script:

biplist - which can be installed using sudo easy_install biplist
Pillow - which can be installed using pip


Optional library for excel output- xlsxwriter which can be installed using easy_install

Usage:

TSV output:

python quicklook_parser.py -d "C:\com.apple.QuickLook.thumbnailcache" -o "C:\report_folder"

Excel output:

python quicklook_parser.py -d "C:\com.apple.QuickLook.thumbnailcache" -o "C:\report_folder" -t excel

Grab the resources folder if you want the pretty icon for the GUI

Blog post:
 
http://az4n6.blogspot.com/2016/05/quicklook-python-parser-all-your-blobs.html

 

