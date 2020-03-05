This plugin extracts and analyzes forensic artifacts from a iOS system, used in iPhones and iPads.


## Creating iOS backups

The main input for the jobs in this plugin is an iOS backup. You can create this backup using iTunes or idevicebackup2 from the libimobile library (<https://www.libimobiledevice.org/>). Encrypted backups are preferred, since they include additional information not present in regular backups.

```bash
idevicebackup2 encryption on "PASSWORD"
idevicebackup2 backup .
idevicebackup2 encryption off "PASSWORD"
```

You *need* the backup password. Write it down somewhere.

The *path* to the main job is the path to the folder containing the backup, or a .zip file containing the backup.

Save the backup as the folder `%(imagedir)s/CASE_NAME/SOURCE_NAME` or zip file `%(imagedir)s/images/CASE_NAME/SOURCE_NAME.zip`.

If the backup is encrypted, and additinal step to decrypt the backup is needed. Currently, the RVT2 does not include directly the tools to decrypt an iOS backup and you must install an external tool such as <https://github.com/dinosec/iphone-dataprotection>. Once installed, add this configuration to the RVT2:

```ini
[ios.unback]
unback_command: PATH_TO_BACKUPTOOL//backup_tool.py {bk_path} {extract_path}
```