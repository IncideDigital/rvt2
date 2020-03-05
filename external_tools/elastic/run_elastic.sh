#!/bin/bash
# Usage: ./run_elastic.sh [IP_ADDRESS]
# If an IP address is not provided, use all interfaces

IFACE_NAME=eth0
NODE_NAME=node-portable
CLUSTER_NAME=rvt2-portable

# get the most modern elasticsearch version in the directory
if [ -z "$ELASTIC_HOME"]; then
    ELASTIC_HOME=$(ls -d elasticsearch-*|sort|tail -n1)
fi

echo "Running $ELASTIC_HOME"

echo 'WARNING: if elastic does not start, try the next command (it will open a new bash session) and then run again'
echo 'COMMAND: sudo sh -c "ulimit -c unlimited && exec su $LOGNAME"'


if [ -z "$1" ]; then
    #MYIP=$(/sbin/ip addr list $IFACE_NAME | awk '/inet /{print $2}' | cut -d/ -f1)
    MYIP="0.0.0.0"
else
    MYIP=$1
fi
echo "Using IP: $MYIP"

if [[ $ELASTIC_HOME =~ elasticsearch-7 ]]; then
    # Elastic 7.X needs an explicit definition of the master nodes
    EXTRA_CONF="-E cluster.initial_master_nodes=$NODE_NAME"
fi


sudo sysctl -w vm.max_map_count=262144
"./$ELASTIC_HOME/bin/elasticsearch" \
    -E node.name=$NODE_NAME \
    -E cluster.name=$CLUSTER_NAME \
    -E network.host=$MYIP \
    -E http.cors.enabled=true \
    -E http.cors.allow-origin="*" $EXTRA_CONF
