#!/bin/bash
# Recover a backed up index

INDEXNAME=$1
if [ -z "$INDEXNAME" ]; then
    echo "Usage: $0 INDEXNAME [ESSERVER]"
    exit 1
fi
if [ -z "$2" ]; then
    ESSERVER=http://localhost:9200
else
    ESSERVER=$2
fi

if [ -z "$(curl -XGET $ESSERVER/$INDEXNAME 2>/dev/null | grep '\"status\":404')" ]; then
  echo 'The index already exists. Are you sure you want to recover it?'
  echo "If you do, run: curl -XDELETE $ESSERVER/$INDEXNAME"
  exit 1
fi

elasticdump --output $ESSERVER/$INDEXNAME --input $INDEXNAME.mapping.json --type mapping
elasticdump --output $ESSERVER/$INDEXNAME --input $INDEXNAME.json --type data
# save information about the case in rvtindexer
if [ -e "$INDEXNAME.rvtindexer.json" ]; then
  elasticdump --output $ESSERVER/rvtindexer --input $INDEXNAME.rvtindexer.json --type data
fi
