#!/bin/bash

# Script with functions to setup a Debian Stretch environment ready for RVT2.
# Functions included do next:
# - Setup folders, users, sudoers.
# - Install necessary packages from APT to build dependencies.
# - Install python3 and pip from APT to run rvt2 and install rvt2 module dependencies.
# - Install rvt2 binary dependencies from APT (those that aren't python3 modules).
# - Download, build and install rvt2 binary dependencies that aren't available in Debian Stretch.

# TODO: give user permissions to group 'disk'

set -ex

RVT2HOME="/opt/rvt2"
SRCDIR="/usr/local/src"
BASEDIR=$(pwd)

# Update apt database
prepare_debian() {
    apt-get update
}

# Prepare RVT2 folders
prepare() {
    mkdir -p "${RVT2HOME}"
    mkdir -p "${SRCDIR}"
}

prepare_copy() {
    cp -rp * "${RVT2HOME}"
}


# Install Debian build tools
install_debian_buildtools() {
    apt-get install -y \
        unzip p7zip-full wget git \
        build-essential debhelper apt-utils fakeroot cmake \
        cargo rustc \
        python3-all-dev \
        pkg-config libssl-dev autotools-dev zlib1g-dev
}

# Install Debian useful tools
install_debian_utils() {
    apt-get install -y \
        sudo curl vim less procps jq \
        ripgrep tree \
        p7zip bzip2 libbz2-dev \
        gnupg dirmngr
}

# Install rvt2 dependencies available in Debian
install_debian_deps() {
    apt-get install -y \
        bindfs dislocker ewf-tools libewf-dev testdisk \
        libimage-exiftool-perl \
        fuse3 libfuse3-dev libfuse-dev libicu-dev libattr1-dev
    apt-get install -y libparse-win32registry-perl # regripper
}

# Install python3 and pip3
install_debian_python() {
    apt-get install -y python3 python3-pip python3-setuptools
}

# Install rvt2 python dependencies
install_pip_deps() (
    # these dependencies fail in the Dockerfile
    python3 -m pip install lz4
    python3 -m pip install evtx
    python3 -m pip install pipenv
    python3 -m pip install pycrypto
    export LC_ALL=C.UTF-8
    export LANG=C.UTF-8
    cd "${RVT2HOME}"
    env PIPENV_VENV_IN_PROJECT=1 pipenv --python /usr/bin/python3
    pipenv install
)

build_install_evtx() (
    cd "${SRCDIR}"
    EVTX=$(curl --silent "https://api.github.com/repos/omerbenamram/evtx/releases/latest"| grep -oP '"browser_download_url": "\K(.*)(?=")' |grep linux-gnu| grep x86_64)
    wget $EVTX
    chmod 755 evtx_dump*
    mv evtx_dump* /usr/local/bin/evtx_dump
)

build_install_sleuthkit() (
    cd "${SRCDIR}"
    SLEUTHKIT=$(curl --silent "https://api.github.com/repos/sleuthkit/sleuthkit/releases/latest" | grep -oP '"browser_download_url": "\K(.*)(?=")'| grep "tar.gz$")
    wget $SLEUTHKIT
    FILENAME=${SLEUTHKIT##*/}
    tar xzvf $FILENAME
    rm $FILENAME
    cd "${FILENAME%.tar.gz}"
    ./configure
    make
    make install
)

build_install_sleuthkit_APFS() (
    cd "${SRCDIR}"
    git clone "https://github.com/blackbagtech/sleuthkit-APFS.git"
    cd sleuthkit-APFS
    ./bootstrap
    ./configure
    make
)

# Verify the download hash
_download_verify() (
    # Download the contents of $1 and verify that the sha256 matches $2.
    # If the hash doesn't match, return 1.
    local url="$1"
    local sha256="$2"
    local filename=$(basename "$url")
    cd "${SRCDIR}"
    wget "${url}"
    local calc_sha256="`sha256sum ${filename} | cut -d' ' -f1`"
    if [ "${calc_sha256}" = "${sha256}" ]; then
       echo "Good sha256 for ${url}"
    else
       echo "Bad sha256 for ${url}"
       echo "Expected: ${sha256}"
       echo "Got:      ${calc_sha256}"
       return 1
    fi
)

# GPG integrity check
_check_signature_libyal() (
    local TARFILE="$1"
    local ASCFILE="$2"
    cd "${SRCDIR}"
    ID=$(gpg "${ASCFILE}" | grep "RSA" | awk '{print $NF}')
    gpg --keyserver "hkp://keyserver.ubuntu.com" --recv-keys "${ID}"
    if [[ -n "$(gpg --verify ${ASCFILE} ${TARFILE} | grep '\"Joachim Metz <joachim.metz@gmail.com>\"')" ]]
    then
      echo "Good Signature"
    else
      echo "Fail in GPG signature of ${ASCFILE}"
      echo "Expected: Good signature from \"Joachim Metz <joachim.metz@gmail.com>\""
      return 1
    fi
)

_build_install_libyal() (
    local NAME="$1"
    local STAGE="$2"
    local VER="$3"
    local TARFILE="https://github.com/libyal/${NAME}/releases/download/${VER}/${NAME}-${STAGE}-${VER}.tar.gz"
    local ASCFILE="${TARFILE}.asc"

    cd "${SRCDIR}"
    wget "${TARFILE}"

    # libpff does not have GPG signature
    if [ "${NAME}" != "libpff" ]; then
      wget "${ASCFILE}"
      # _check_signature_libyal ${NAME}-${STAGE}-${VER}.tar.gz ${NAME}-${STAGE}-${VER}.tar.gz.asc
    fi

    ln -s ${NAME}-${STAGE}-${VER}.tar.gz ${NAME}_${VER}.orig.tar.gz
    tar xzf ${NAME}-${STAGE}-${VER}.tar.gz
    cd ${NAME}-${VER}/
    ./configure --enable-python
    make
    make install
    ldconfig
    cd ..
)

build_install_libesedb() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libesedb/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libesedb experimental "${VERSION}"
}

build_install_liblnk() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/liblnk/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal liblnk alpha "${VERSION}"
}

build_install_libmsiecf() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libmsiecf/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libmsiecf alpha "${VERSION}"
}

build_install_libscca() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libscca/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libscca alpha "${VERSION}"
}

build_install_libpff() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libpff/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libpff alpha "${VERSION}"
}

build_install_libvshadow() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libvshadow/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libvshadow alpha "${VERSION}"
    # sed -i "s/.user_allow_other/user_allow_other/" /etc/fuser.conf
}

build_install_libfvde() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libfvde/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libfvde experimental "${VERSION}"
    # sed -i "s/.user_allow_other/user_allow_other/" /etc/fuser.conf
}

build_install_libevt() {
    local VERSION=$(curl -s "https://api.github.com/repos/libyal/libevt/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libevt alpha "${VERSION}"
}

build_install_volatility() {
    cd "${SRCDIR}"
    git clone https://github.com/volatilityfoundation/volatility3.git
    ln -s "$(pwd)"/volatility3/vol.py /usr/local/bin/vol.py
    mkdir -p volatility3/symbols
    wget -O volatility3/symbols/windows.zip https://downloads.volatilityfoundation.org/volatility3/symbols/windows.zip
    wget -O volatility3/symbols/mac.zip https://downloads.volatilityfoundation.org/volatility3/symbols/mac.zip
    wget -O volatility3/symbols/linux.zip https://downloads.volatilityfoundation.org/volatility3/symbols/linux.zip
}

build_install_regripper() (
    local NAME="RegRipper3.0"
    local COMMIT="c59d23d151059aa98f1888ee52e2eea16f746f21"
    [ -d /tmp/patches ] || cp -rp patches /tmp/
    cd "${SRCDIR}"
    _download_verify "https://github.com/keydet89/${NAME}/archive/${COMMIT}.zip" \
        "db7040058e80fe816e2a8936a29c5a62ebab235eec0870d306453832a0343335"
    mv "${COMMIT}".zip ${NAME}-${COMMIT}.zip
    unzip ${NAME}-${COMMIT}.zip
    cd ${NAME}-${COMMIT}

    patch rip.pl < /tmp/patches/regripper_patch.diff

    install -p -dm 755 /opt/regripper/
    install -p -m 755 *.pl *.txt *.md /opt/regripper/
    install -p -dm 755 /opt/regripper/plugins/
    install -p -m 755 plugins/* /opt/regripper/plugins/
    install -p -m 755 /tmp/patches/regripper_plugins/ccleaner.pl \
          /tmp/patches/regripper_plugins/cortana.pl \
          /tmp/patches/regripper_plugins/defbrowser.pl \
          /tmp/patches/regripper_plugins/diag_sr.pl \
          /tmp/patches/regripper_plugins/eventlog.pl \
          /tmp/patches/regripper_plugins/eventlogs.pl \
          /tmp/patches/regripper_plugins/fw_config.pl \
          /tmp/patches/regripper_plugins/ie_settings.pl \
          /tmp/patches/regripper_plugins/ie_version.pl \
          /tmp/patches/regripper_plugins/outlook_search.pl \
          /tmp/patches/regripper_plugins/polacdms.pl \
          /tmp/patches/regripper_plugins/proxysettings.pl \
          /tmp/patches/regripper_plugins/rdphint.pl \
          /tmp/patches/regripper_plugins/rdpnla.pl \
          /tmp/patches/regripper_plugins/silentprocessexit.pl \
          /tmp/patches/regripper_plugins/silentprocessexit_tln.pl \
          /tmp/patches/regripper_plugins/teamviewer.pl \
          /tmp/patches/regripper_plugins/vmware_vsphere_client.pl \
          /tmp/patches/regripper_plugins/winevt.pl \
          /tmp/patches/regripper_plugins/winlogon_db.pl \
          /tmp/patches/regripper_plugins/winnt_cv.pl \
          /tmp/patches/regripper_plugins/winscp_sessions.pl \
          /tmp/patches/regripper_plugins/crashcontrol.pl \
          /tmp/patches/regripper_plugins/winver2.pl \
        /opt/regripper/plugins/
    install -p -dm 755 /usr/local/bin/
    ln -s /opt/regripper/rip.pl /usr/local/bin/rip
    rm -r /tmp/patches

    # Replaces Base, File and Key.pm with regripper version

    local WIN32REGISTRY=$(dirname $(dpkg -L libparse-win32registry-perl|grep "/Base.pm"))
    if [ -e Base.pm ]; then
        sudo cp -np "$WIN32REGISTRY/Base.pm" "$WIN32REGISTRY/Base.pm.old"
        sudo cp -p Base.pm "$WIN32REGISTRY"
    fi
    if [ -e File.pm ]; then
        sudo cp -np "$WIN32REGISTRY/WinNT/File.pm" "$WIN32REGISTRY/WinNT/File.pm.old"
        sudo cp -p File.pm "$WIN32REGISTRY/WinNT/"
    fi
    if [ -e Key.pm ]; then
        sudo cp -np "$WIN32REGISTRY/WinNT/Key.pm" "$WIN32REGISTRY/WinNT/Key.pm.old"
        sudo cp -p Key.pm "$WIN32REGISTRY/WinNT/"
    fi
)

build_install_ntfs3g_system_compression() (
    local NAME="ntfs-3g-system-compression"
    local VER="1.0"
    apt install ntfs-3g-dev
    cd "${SRCDIR}"
    _download_verify "https://github.com/ebiggers/${NAME}/releases/download/v${VER}/${NAME}-${VER}.tar.gz" \
        "c4a26f3a704f5503ec1b3af5e4bb569590c6752616e68a3227fc717417efaaae"
    tar xzf ${NAME}-${VER}.tar.gz
    cd ${NAME}-${VER}/
    ./configure
    make
    make install
)

build_install_apfs_fuse() (
    cd "${SRCDIR}"
    git clone https://github.com/sgan81/apfs-fuse.git
    cd apfs-fuse
    git submodule init
    git submodule update
    mkdir build
    cd build
    cmake ..
    make
    ln -s ${SRCDIR}/apfs-fuse/apfs-fuse /usr/local/bin/apfs-fuse
    ln -s ${SRCDIR}/apfs-fuse/apfs-dump /usr/local/bin/apfs-dump
    ln -s ${SRCDIR}/apfs-fuse/apfs-dump-quick /usr/local/bin/apfs-dump-quick
)

build_install_yara() (
    cd "${SRCDIR}"
    YARA=$(curl --silent "https://api.github.com/repos/VirusTotal/yara/releases/latest" | grep -oP '"tarball_url": "\K(.*)(?=")')
    wget $YARA
    FILENAME=${YARA##*/}
    tar xzvf $FILENAME
    rm $FILENAME
    mv VirusTotal-yara-* yara-$FILENAME
    cd yara-$FILENAME

    ./bootstrap.sh
    apt-get install -y flex bison libjansson-dev libmagic-dev
    ./configure --with-crypto --enable-cuckoo --enable-magic --enable-dotnet
    make
    make install
)

# Clone submodules and make some patches to submodules in order to work as RVT2 expects
submodules() (
    git submodule init
    git submodule update
    # srumpdump includes a graphical interface not needed in RVT2
    sed '19d' plugins/external/srum-dump/srum_dump2.py > tempfile && mv tempfile plugins/external/srum-dump/srum_dump2.py
)

install_zimmerman_tools(){
# dotnet installation
    cd "${RVT2HOME}"
    EXTERNAL_PATH="external_tools"
    mkdir -p $EXTERNAL_PATH/dotnet
    mkdir $EXTERNAL_PATH/windows
    wget https://dot.net/v1/dotnet-install.sh -O dotnet-install.sh
    chmod +x ./dotnet-install.sh 
    ./dotnet-install.sh -c 6.0 --runtime dotnet -i $EXTERNAL_PATH/dotnet
    rm ./dotnet-install.sh
    # Zimmerman tools
    cd $EXTERNAL_PATH
    cd windows
    for tool in "AmcacheParser" "AppCompatCacheParser" "MFTECmd" "SBECmd" "SrumECmd" "WxTCmd"
      do
        mkdir $tool
        cd $tool
        wget https://f001.backblazeb2.com/file/EricZimmermanTools/net6/${tool}.zip
        7z x $tool.zip
        rm $tool.zip
        cd ..
      done
    for tool in "SDBExplorer" "RECmd"
      do
        wget https://f001.backblazeb2.com/file/EricZimmermanTools/net6/${tool}.zip
        7z x $tool.zip
        rm $tool.zip
      done
    cd ..
}

install_rvt_bin() {
    cat << EOF > /usr/local/bin/rvt2
#!/bin/sh

sudo -u rvt -g rvt /opt/rvt2/rvt2 "\$@"
EOF
    chmod +x /usr/local/bin/rvt2
}

# Add rvt user and allow execution of special programs as root
prepare_sudo() {
    useradd --user-group --create-home --shell /bin/bash rvt
    APPS='/bin/mount, /bin/umount, /sbin/losetup, /usr/local/bin/vshadowmount, /usr/bin/bindfs, /usr/local/bin/icat, /usr/local/bin/apfs-fuse'
    echo "%rvt ALL=(root) NOPASSWD: ${APPS}" >> /etc/sudoers
}

# Give /morgue group rvt permissions
prepare_morgue() {
    mkdir /morgue
    chown rvt:rvt /morgue
    chmod 775 /morgue
}

# Links rvt2 executable to /usr/local/bin
create_link_bin() {
    ln -s /opt/rvt2/rvt2 /usr/local/bin/rvt2
}

# Remove unnecessary source files
clean_sources() (
  cd "${SRCDIR}"
  rm -rf libvshadow* libesedb* libpff* libfvde* libscca* libevt* apfs-fuse ntfs-3g* liblnk libmsiecf
  rm -f Parse-Evtx*.zip* RegRipper2*
)

# Use this function to install all dependencies on ubuntu 22.04 and setup rvt2
setup_debian_full() {

    # Basic preparation
    prepare_debian
    prepare
    prepare_copy

    # Debian Tools
    install_debian_buildtools
    install_debian_utils
    install_debian_deps
    install_debian_python

    # Download submodules
    submodules

    install_zimmerman_tools

    # Extra Tools
    build_install_sleuthkit
      # build_install_sleuthkit_APFS
    build_install_libesedb
    build_install_libpff
    build_install_libvshadow
    build_install_libfvde
    build_install_liblnk
    build_install_libmsiecf
    build_install_libscca
    build_install_libevt
    build_install_regripper
    # build_install_ntfs3g_system_compression
    build_install_apfs_fuse
    build_install_yara
    build_install_volatility
    build_install_evtx

    # Install pip dependencies
    install_pip_deps

    # Permissions and links
    prepare_sudo
    prepare_morgue
      # install_rvt_bin
    create_link_bin
    clean_sources
}

# Dummy functions related to old dependencies. rvt2-docker still calls them

build_install_evtxparser() {
  :
}

if [ "$1" = "run" ]; then
  setup_debian_full
fi
