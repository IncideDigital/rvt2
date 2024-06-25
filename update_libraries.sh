#!/bin/bash

# Script with functions to update libraries used by RVT2.

set -ex

RVT2HOME="/usr/local/rvt2"
SRCDIR="/usr/local/src"
BASEDIR=$(pwd)

update_evtx() (
    cd "${SRCDIR}"
    EVTX=$(curl --silent "https://api.github.com/repos/omerbenamram/evtx/releases/latest"| grep -oP '"browser_download_url": "\K(.*)(?=")' |grep linux-gnu)
    wget $EVTX
    chmod 755 evtx_dump*
    mv evtx_dump* /usr/local/bin/evtx_dump
)

update_sleuthkit() (
    cd "${SRCDIR}"
    SLEUTHKIT=$(curl --silent "https://api.github.com/repos/sleuthkit/sleuthkit/releases/latest" | grep -oP '"browser_download_url": "\K(.*)(?=")'| grep "tar.gz$")
    VERSION=$(echo "$SLEUTHKIT" | sed 's|.*/\(sleuthkit[0-9.-][0-9.-]*\)/.*|\1|')
    if [ ! -d "$VERSION" ]; then
        mkdir -p temp
        [ -d sleuthkit* ] && mv sleuthkit* temp
        wget $SLEUTHKIT
        FILENAME=${SLEUTHKIT##*/}
        tar xzvf $FILENAME
        rm $FILENAME
        cd ${FILENAME::-7}
        ./configure
        make && sudo make install
        retVal=$?
        if [ $retVal -ne 0 ]; then
            echo "Error installing sleuthkit"
	    cd ..
	    rm -rf sleuthkit*
            [ -d temp/sleuthkit* ] && mv temp/sleuthkit* .
        else
            echo "sleuthkit updated successfully"
	    cd ..
	    [ -d temp/sleuthkit* ] && rm -rf temp/sleuthkit*
        fi
    else
        echo "sleuthkit is in the latest version"
    fi
)

update_libyal() (
    local NAME="$1"
    local TARFILE=$(curl -s "https://api.github.com/repos/libyal/$NAME/releases" | grep -oP '"browser_download_url":\s*"\K(.*)(?=")'| grep "tar.gz$" | head -1) 
    local VER=$(echo $TARFILE | sed -rn "s/.*([0-9]{8}).*/\1/p")
    local STAGE=$(echo $TARFILE | sed "s/.*$1-\(.*\)-$VER.tar.gz/\1/")

    cd "${SRCDIR}"
    if [ ! -d "$NAME-$VER" ]; then
	    mkdir -p temp
        [ -d $1* ] && mv $1* temp
        wget "${TARFILE}"

        tar xzf ${NAME}-${STAGE}-${VER}.tar.gz
        cd ${NAME}-${VER}/
	./configure --enable-python3
        make && sudo make install
	retVal=$?
        if [ $retVal -ne 0 ]; then
            echo "Error installing $NAME"
	    cd ..
	    rm -rf $NAME*
            [ -d temp/$NAME* ] && mv temp/$NAME* .
        else
            echo "$NAME updated successfully"
	    sudo ldconfig
	    cd ..
	    [ -d temp/$NAME* ] && rm -rf temp/$NAME*
        fi
    else
        echo "$NAME is in the latest version"
    fi
)

update_volatility3() {
    cd "${SRCDIR}/volatility3"
    git pull origin develop
    wget -O volatility3/symbols/windows.zip https://downloads.volatilityfoundation.org/volatility3/symbols/windows.zip
    wget -O volatility3/symbols/mac.zip https://downloads.volatilityfoundation.org/volatility3/symbols/mac.zip
    wget -O volatility3/symbols/linux.zip https://downloads.volatilityfoundation.org/volatility3/symbols/linux.zip
}

update_yara() {
    cd "${SRCDIR}"
    YARA=$(curl --silent "https://api.github.com/repos/VirusTotal/yara/releases/latest" | grep -oP '"tarball_url": "\K(.*)(?=")')
    VERSION=$(echo "$YARA" | sed 's|.*/\(v[0-9.][0-9.]*\)|\1|')
    if [ ! -d "yara-$VERSION" ]; then
        mkdir -p temp
        [ -d yara* ] && mv yara* temp
        wget $YARA
        FILENAME=${YARA##*/}
        tar xzvf $FILENAME
        rm $FILENAME
	mv VirusTotal-yara-* yara-$FILENAME
        cd yara-${FILENAME}
	./bootstrap.sh
        ./configure --with-crypto --enable-cuckoo --enable-magic --enable-dotnet
        make && sudo make install
        retVal=$?
        if [ $retVal -ne 0 ]; then
            echo "Error installing yara"
	    cd ..
	    rm -r yara*
            [ -d yara* ] && mv temp/yara* .
        else
            echo "yara updated successfully"
	    cd ..
	    [-d temp/yara* ] && rm -r temp/yara*
        fi
    else
        echo "yara is in the latest version"
    fi
}

update_zimmerman_tools() {
    cd "${RVT2HOME}"
    EXTERNAL_PATH="external_tools"
    # Zimmerman tools
    cd $EXTERNAL_PATH
    cd windows
    for tool in "AmcacheParser" "AppCompatCacheParser" "MFTECmd" "SBECmd" "SrumECmd" "WxTCmd"
      do
        cd $tool
	VERSION=$(../../dotnet/dotnet $tool.dll --version)
	NEWVERSION=$(curl https://ericzimmerman.github.io/index.md| sed -n "s|.*\[\([0-9.][0-9.]*\)\].https://f001.backblazeb2.com/file/EricZimmermanTools/net6/$tool.zip.*|\1|p")
	if [ $VERSION != $NEWVERSION ]; then
	    wget https://f001.backblazeb2.com/file/EricZimmermanTools/net6/${tool}.zip
            7z x -y $tool.zip
            rm $tool.zip
            cd ..
	    echo "$tool updated from version $VERSION to $NEWVERSION"
	else
	    echo "$tool is in the latest version"
	    cd ..
	fi
      done
    for tool in "RECmd" "SDBExplorer"
      do
	cd $tool
        VERSION=$(../../dotnet/dotnet $tool.dll --version)
	NEWVERSION=$(curl https://ericzimmerman.github.io/index.md| sed -n "s|.*\[\([0-9.][0-9.]*\)\].https://f001.backblazeb2.com/file/EricZimmermanTools/net6/$tool.zip.*|\1|p")
	if [ $VERSION != $NEWVERSION ]; then
            wget https://f001.backblazeb2.com/file/EricZimmermanTools/net6/${tool}.zip
            7z x -y $tool.zip
            rm $tool.zip
	    cd ..
	    echo "$tool updated from version $VERSION to $NEWVERSION"
	else
	    echo "$tool is in the latest version"
	    cd ..
        fi
      done
    cd ..
}

update_dotnet() {
    cd "${RVT2HOME}"
    EXTERNAL_PATH="external_tools"
    # Zimmerman tools
    cd $EXTERNAL_PATH
    cd dotnet
    VERSION=$(./dotnet --info |sed -n "s/.*Version:[ \t]*\([0-9.]*\)/\1/p")
    wget https://dot.net/v1/dotnet-install.sh -O dotnet-install.sh
    chmod +x ./dotnet-install.sh 
    NEWVERSION=$(./dotnet-install.sh -c 6.0 --runtime dotnet --dry-run | sed -n 's/.*--version "\([^"]*\)".*/\1/p')
    if [ $VERSION != $NEWVERSION ]; then
	./dotnet-install.sh -c 6.0 --runtime dotnet -i .
        echo "dotnet updated from version $VERSION to $NEWVERSION"
    else
        echo "dotnet is in the latest version"
    fi
}
update_sleuthkit
update_libyal libesedb
update_libyal liblnk
update_libyal libmsiecf
update_libyal libscca
update_libyal libpff
update_libyal libvshadow
update_libyal libfvde
update_libyal libvmdk
update_libyal libvslvm
update_libyal libevt
update_libyal libvhdi

update_volatility3
update_yara
update_dotnet
update_zimmerman_tools

