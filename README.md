# Revealer Toolkit 2

![](docs/data/rvt2_logo.png)

## Introduction

Revealer Toolkit 2 (RVT2) is a framework for computer forensics. It is written in Python 3 and internally many open source tools like The Sleuth Kit or regripper.

RVT2 aims to automate rutinary tasks and analysis when managing forensic images, or sources. RVT2 is specially useful in an environment with many cases and many sources.

RVT2 is developed and continously used in [INCIDE](https://www.incide.es/), a Spanish DFIR company sited at the beautiful city of Barcelona.

It is designed to run on Debian Buster stable version, but can also be installed with `docker` if desired.

The analyst/user manual for RVT2 is available at [rvt2-docs](https://incidedigital.github.io/rvt2-docs). For a more in depth description of the modules, packages and classes in the RVT2, check the Developers manual [rvt2-devel](https://incidedigital.github.io/rvt2) (soon to be realeased).

## Installation

Currently, there are two ways to install RVT2:
  * Via Docker
  * Standalone Version

### Docker

RVT2 can be started with `docker` using the build at [rvt2-docker](https://github.com/IncideDigital/rvt2-docker). Follow the instructions described in the repository to run RVT2 `with docker`.

### Standalone

RVT2 is designed to run on Debian Buster stable version, althought it is possible to install it on other other GNU-Linux flavours.

These commands will clone the RVT2 source code and install the external dependencies:

```bash
git clone https://github.com/IncideDigital/rvt2.git
cd rvt2
sudo bash setup.sh run
```

The directory where the RVT2 was cloned will be referred as the `$RVT2_HOME` directory in this documentation.

RVT2 manages the Python dependencies or the core plugins internally. The first time the RVT2 is run, it will create a pyenv environment and install these dependecies. As a result, the first run of the RVT2 will be very slow!

If you prefer a manual installation of the Python dependencies, run these commands from the $RVT2_HOME directory.

```bash
pip3 install --user pipenv
pipenv --three
pipenv install
```

### External tools

Some plugins may need additional external tools. For example:

* indexer: The indexer needs Tika and ElasticSearch. An easy installation can be executed with the scripts provided in the `external_tools` folder.
* ai: Image classification models must be downloaded. Read [INSTALL.md](plugins/ai/INSTALL.ai) for more information.

In addition, if you download additional plugins, be sure to check their documentation for any additional plugins they might need.

### Permissions

RVT2 uses many system commands (such as mount) that must executed with root privileges. This is not a problem if the analyst is the only user of the machine.

In a multi-user environment, you might consider adding some extra security to prevent analysts to be root of the machine. Add a rvt user and analysts group to your OS:

```bash
groupadd analysts
useradd -M -N -s /bin/false -r -G analyst rvt
```

Change loopdevices permissions to allow members of the analyst group to read from them:

```bash
echo "for i in $(seq 8 31) ; do mknod -m 660 /dev/loop$i b 7 $i ; done\nchgrp analysts /dev/loop*" > /etc/rc.local
```

Edit /etc/sudoers with visudo and allow the rvt user to run these commands without promping for a password:

```
%analyst (rvt) NOPASSWD: $RVT2_HOME/rvt2/rvt2
rvt ALL=(root) NOPASSWD: /bin/mount, /bin/umount, /sbin/losetup, /usr/local/bin/vshadowmount, /usr/bin/bindfs, /usr/local/bin/icat
```

Then, run rvt2 command as rvt user:

```bash
sudo -u rvt $RVT2_HOME/rvt2 [options]
```

Finally, it is recommended that directories storing information about a case must have the user rvt as owner and the group analyst with reading permissions but not writing.

## Basic Usage

Most of the time, you are going to run one of the predefined jobs with the default configuration. For example, to index the content of a disk in ElasticSearch, run:

```bash
rvt2 \
    --casename 112233 --source 01 \
    -j indexer.save_directory \
    --params option1=1 option2 -- \
    path_to_a_directory
```

There are dozens of predefined jobs with a default configuration you won't need to change. You can get the list of predefined by running the job show_jobs, which is also the default job:

```bash
rvt2
```
