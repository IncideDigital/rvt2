#!/bin/bash

# This script contains functions to setup a Debian Stretch environment to use rvt2 on it.
# It contains functions that:
# - setup folders, users, sudoers.
# - install necessary packages from APT to build dependencies.
# - install python3 and pip from APT to run rvt2 and install rvt2 module dependencies.
# - install rvt2 binary dependencies from APT (those that aren't python3 modules).
# - download, build and install rvt2 binary dependencies that aren't available in Debian Stretch.

# TODO: give user permissions to group 'disk'

set -ex

RVT2HOME="/opt/rvt2"
SRCDIR="/usr/local/src"
BASEDIR=$(pwd)

# Update apt database
prepare_debian() {
    apt-get update
}

prepare() {
    mkdir -p "${RVT2HOME}"
    mkdir -p "${SRCDIR}"
}

prepare_copy() {
    cp -rp * "${RVT2HOME}"
}

# Install python3 and pip3
install_debian_python() {
    apt-get install -y python3 python3-pip python-setuptools python3-setuptools
}

# Install rvt2 python dependencies
install_pip_deps() (
    pip3 install lz4
    pip3 install pipenv
    export LC_ALL=C.UTF-8
    export LANG=C.UTF-8
    cd "${RVT2HOME}"
    env PIPENV_VENV_IN_PROJECT=1 pipenv --python /usr/bin/python3
    pipenv install
)

# Install Debian build tools
install_debian_buildtools() {
    apt-get install -y \
        unzip wget \
        build-essential debhelper fakeroot python-all-dev python3-all-dev \
        pkg-config libssl-dev autotools-dev zlib1g-dev git
}

# Install Debian useful tools
install_debian_utils() {
    apt-get install -y \
        vim procps less dislocker silversearcher-ag sleuthkit
}

# Install rvt2 dependencies available in Debian
install_debian_deps() {
    apt-get install -y \
        sudo \
        bindfs \
        p7zip \
        cmake \
        volatility volatility-tools \
        libimage-exiftool-perl \
        testdisk \
        libscca1 libscca-utils python3-libscca \
        libmsiecf1 libmsiecf-utils python3-libmsiecf \
        liblnk1 liblnk-utils python3-liblnk
    apt-get install -y libparse-win32registry-perl # regripper
    apt-get install -y libdatetime-perl libcarp-assert-perl # Evtx-Parser
    apt-get install -y fuse libfuse-dev libicu-dev bzip2 libbz2-dev libattr1-dev
    apt-get install -y curl gnupg dirmngr tree
    apt-get install -y ewf-tools fd-find
}

# Download the contents of $1 and verify that the sha256 matches $2.
# If the hash doesn't match, return 1.
_download_verify() (
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
    cp -rf dpkg debian
    dpkg-buildpackage -uc -us -rfakeroot
    cd ..
    dpkg -i ${NAME}_*.deb ${NAME}-tools_*.deb ${NAME}-python3_*.deb
)

build_install_libesedb() {
    local VERSION=$(curl -s "https://github.com/libyal/libesedb/releases" \
    | grep "libesedb-experimental-.*.tar.gz" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libesedb experimental "${VERSION}"
}

build_install_libpff() {
    local VERSION=$(curl -s "https://github.com/libyal/libpff/releases" \
    | grep "libpff-experimental-.*.tar.gz" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libpff experimental "${VERSION}"
}

build_install_libvshadow() {
    local VERSION=$(curl -s "https://github.com/libyal/libvshadow/releases" \
    | grep "libvshadow-alpha-.*.tar.gz" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libvshadow alpha "${VERSION}"
    # sed -i "s/.user_allow_other/user_allow_other/" /etc/fuser.conf
}

build_install_libfvde() {
    local VERSION=$(curl -s "https://github.com/libyal/libfvde/releases" \
    | grep "libfvde-alpha-.*.tar.gz" | head -1 \
    | sed -rn "s/.*([0-9]{8}).*/\1/p")

    _build_install_libyal libfvde alpha "${VERSION}"
    # sed -i "s/.user_allow_other/user_allow_other/" /etc/fuser.conf
}

build_install_sleuthkit() (
    cd "${SRCDIR}"
    git clone "https://github.com/sleuthkit/sleuthkit.git"
    cd sleuthkit
    ./bootstrap
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

build_install_regripper() (
    local NAME="RegRipper2.8"
    local COMMIT="ee874d5245fb4f26147c29dc1db02b8e68a88698"
    cd "${SRCDIR}"
    _download_verify "https://github.com/keydet89/${NAME}/archive/${COMMIT}.zip" \
        "9cea8786588417b89a6f9497d8d97222f5f7daeaf276b40a2cd02157ea121b2e"
    mv "${COMMIT}".zip ${NAME}-${COMMIT}.zip
    unzip ${NAME}-${COMMIT}.zip
    cd ${NAME}-${COMMIT}
    [ -d /tmp/patches ] || cp -rp patches /tmp/

    patch rip.pl < /tmp/patches/regripper_patch.diff

    install -p -dm 755 /opt/regripper/
    install -p -m 755 *.pl *.txt *.md *.pdf /opt/regripper/
    install -p -dm 755 /opt/regripper/plugins/
    install -p -m 755 plugins/* /opt/regripper/plugins/
    install -p -m 755 /tmp/patches/regripper_plugins/outlook_search.pl \
	      /tmp/patches/regripper_plugins/winlogon_db.pl \
        /opt/regripper/plugins/
    install -p -dm 755 /usr/local/bin/
    ln -s /opt/regripper/rip.pl /usr/local/bin/rip
    rm -r /tmp/patches

    # Replaces Base, File and Key.pm with regripper version

    local WIN32REGISTRY=$(dirname $(dpkg -L libparse-win32registry-perl|grep "/Base.pm"))
    sudo cp -np "$WIN32REGISTRY/Base.pm" "$WIN32REGISTRY/Base.pm.old"
    sudo cp -p Base.pm "$WIN32REGISTRY"
    sudo cp -np "$WIN32REGISTRY/WinNT/File.pm" "$WIN32REGISTRY/WinNT/File.pm.old"
    sudo cp -p File.pm "$WIN32REGISTRY/WinNT/"
    sudo cp -np "$WIN32REGISTRY/WinNT/Key.pm" "$WIN32REGISTRY/WinNT/Key.pm.old"
    sudo cp -p Key.pm "$WIN32REGISTRY/WinNT/"
)

build_install_evtxparser() (
    local NAME="Parse-Evtx"
    local VER="1.1.1"
    cd "${SRCDIR}"
    echo "yes" | perl -MCPAN -e "install Carp::Assert"
    echo "yes" | perl -MCPAN -e "install DateTime"
    echo "yes" | perl -MCPAN -e "install Digest::CRC"
    perl -MCPAN -e "install Data::Hexify"
    _download_verify "https://computer.forensikblog.de/files/evtx/${NAME}-${VER}.zip" \
        "a1909810bedc709e2fa87f6603e52c62e60086bf1ce064bd839fc5873abf8512"
    unzip ${NAME}-1.1.1.zip
    cd ${NAME}-1.1.1
    perl Makefile.PL
    make
    make install
)

build_install_ntfs3g() (
    local NAME="ntfs-3g_ntfsprogs"
    local VER="2017.3.23"
    cd "${SRCDIR}"
    _download_verify "https://tuxera.com/opensource/${NAME}-${VER}.tgz" \
        "3e5a021d7b761261836dcb305370af299793eedbded731df3d6943802e1262d5"
    tar xzf ${NAME}-${VER}.tgz
    cd ${NAME}-${VER}/
    ./configure
    make
    make install
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

build_install_apf_fuse() (
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
    wget https://github.com/VirusTotal/yara/archive/v3.11.0.tar.gz
    tar -zxf v3.11.0.tar.gz
    cd yara-3.11.0
    ./bootstrap.sh
    apt-get install -y flex bison
    ./configure --with-crypto --enable-cuckoo --enable-magic --enable-dotnet
    make
    make install
)

build_install_hindsight() (
    cd ${SRCDIR}
    git clone --depth 1 https://github.com/obsidianforensics/hindsight.git
    cd hindsight
    apt-get install python-pip
    yes | pip install -r requirements.txt  # segment violation during protobuf
    # pip install protobuf scipy xlsxwriter bottle # if segment error
    chmod 775 ${SRCDIR}/hindsight/hindsight.py  # ???
    # make a symbolic link to /usr/local/bin ???
    ln -s ${SRCDIR}/hindsight/hindsight.py /usr/local/bin/hindsight.py
)

install_rvt_bin() {
    cat << EOF > /usr/local/bin/rvt2
#!/bin/sh

sudo -u rvt -g rvt /opt/rvt2/rvt2 "\$@"
EOF
    chmod +x /usr/local/bin/rvt2
}

install_rvt_bin_no_sudo() {
    cat << EOF > /usr/local/bin/rvt2
#!/bin/sh

/opt/rvt2/rvt2 "\$@"
EOF
    chmod +x /usr/local/bin/rvt2
}

# Add rvt user and allow execution of special programs as root
prepare_sudo() {
    useradd --user-group --create-home --shell /bin/bash rvt
    echo '%rvt ALL=(root) NOPASSWD: /bin/mount, /bin/umount, /sbin/losetup, /usr/local/bin/vshadowmount, /usr/bin/bindfs, /usr/local/bin/icat, /usr/local/bin/apfs-fuse' >> /etc/sudoers
}

# Give /morgue group rvt permissions
prepare_morgue() {
    mkdir /morgue
    chown rvt:rvt /morgue
    chmod 775 /morgue
}

create_link_bin() {
    ln -s /opt/rvt2/rvt2 /usr/local/bin/rvt2
}

fix_submodules() {
    cd $RVT2HOME
    # srumpdump includes a graphical interface not needed in RVT2
    sed '19d' plugins/external/srum-dump/srum_dump2.py > tempfile && mv tempfile plugins/external/srum-dump/srum_dump2.py
}

# Remove unnecessary source files
clean_sources() {
  cd "${SRCDIR}"
  rm -rf libvshadow* libesedb* libpff*
  rm -f Parse-Evtx*.zip* RegRipper2*.zip
}

# Use this function to install all dependencies on Debian stretch and setup rvt2
setup_debian_full() {
    prepare_debian
    prepare
    prepare_copy

    install_debian_python
    install_pip_deps
    install_debian_buildtools
    install_debian_utils
    install_debian_deps

    build_install_libesedb
    build_install_libpff
    build_install_libvshadow
    build_install_libfvde

    build_install_sleuthkit
    build_install_sleuthkit_APFS
    build_install_regripper
    build_install_evtxparser
    # build_install_ntfs3g
    build_install_ntfs3g_system_compression
    build_install_apf_fuse
    build_install_yara
    build_install_hindsight

    #install_rvt_bin
    #prepare_sudo
    #prepare_morgue
    fix_submodules
    create_link_bin
    clean_sources
}
