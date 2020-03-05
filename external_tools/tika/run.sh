#!/bin/bash

# Download the tika server if not present in the current directory
JARFILE="tika-server-1.23.jar"
if [ ! -e "$JARFILE" ]; then
    # curl -L "https://apache.rediris.es/tika/$JARFILE" --output "$JARFILE"
    curl -L http://archive.apache.org/dist/tika/$JARFILE --output "$JARFILE"
fi

# Tika 1.19 depends on sqlite-jdbc 3.19.3 (this version exactly)
# Tika 1.20 depends on sqlite-jdbc 3.25.2 (this version exactly)
# Tika 1.21 depends on sqlite-jdbc 3.27.2.1 (this version exactly)
# Tika 1.23 depends on sqlite-jdbc 3.28.0 (this version exactly)
# Check dependencies in: {tika-server-XX.jar}/META-INF/maven/org.apache.tika/tika-parsers/pom.xml
SQLITE_VERSION="3.28.0"
SQLITE_JARFILE="sqlite-jdbc-$SQLITE_VERSION.jar"
if [ ! -e "$SQLITE_JARFILE" ]; then
    curl -L "https://search.maven.org/remotecontent?filepath=org/xerial/sqlite-jdbc/$SQLITE_VERSION/$SQLITE_JARFILE" --output "$SQLITE_JARFILE"
    # Alternate URL (the file has the same hash):
    # curl -L "https://bitbucket.org/xerial/sqlite-jdbc/downloads/$SQLITE_JARFILE" --output "$SQLITE_JARFILE"
fi

CLASSPATH=$SQLITE_JARFILE:$JARFILE
MAINCLASS=org.apache.tika.server.TikaServerCli

# Tika prior to 1.19.1 used jaxb, part of the EE libraries.
# These libraries were deprecated in Java 9 and Java 10, and missing in Java 11.
# Tika 1.19.1 does not use jaxb any more (https://issues.apache.org/jira/browse/TIKA-2743)
# This code is included as a reference
#JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}')
#case $JAVA_VERSION in
#    8.*)
#        # Java 8 includes the EE libraries. No further action is needed.
#        sha256sum -c hashes.txt --ignore-missing || exit 1
#        java -classpath "$CLASSPATH" -jar "$JARFILE" --config=tika.cfg -h 0.0.0.0 --port 9998 ;;
#    9.* | 10.*)
#        # The EE libraries are deprecated in Java 9 and 10. Tika uses jaxb from the EE libraries.
#        # jaxb can still be used if it is explicity loaded from the command line
#        sha256sum -c hashes.txt --ignore-missing || exit 1
#        java --add-modules java.xml.bind -classpath "$CLASSPATH" "$MAINCLASS" --config=tika.cfg -h 0.0.0.0 --port 9998 ;;
#    11.*)
#        # Java 11 does not include the EE libraries any more:  http://jdk.java.net/11/release-notes#JDK-8190378
#        # Download the reference implementation of jaxb
#        curl -L "https://search.maven.org/remotecontent?filepath=javax/xml/bind/jaxb-api/2.4.0-b180830.0359/jaxb-api-2.4.0-b180830.0359.jar" --output jaxb.jar
#        sha256sum -c hashes.txt --ignore-missing || exit 1
#        CLASSPATH=$CLASSPATH:jaxb.jar
#        java -classpath "$CLASSPATH" "$MAINCLASS" --config=tika.cfg -h 0.0.0.0 --port 9998 ;;
#    *) echo "This script was tested in Java 8 to 11. You are using: $JAVA_VERSION"
#esac

sha256sum -c hashes.txt --ignore-missing || exit 1
java -classpath "$CLASSPATH" $MAINCLASS --config=tika.cfg -h 0.0.0.0 --port 9998
