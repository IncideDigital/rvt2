#!/bin/bash
# Backup an index in elastic search

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

# note elasticdump fails if any of these files already exist.
#This is GOOD: we are backing up, do not ovewrite backups

elasticdump --input $ESSERVER/$INDEXNAME --output $INDEXNAME.mapping.json --type mapping
elasticdump --input $ESSERVER/$INDEXNAME --output $INDEXNAME.json --type data
# save information in rvtindexer
elasticdump --input $ESSERVER/rvtindexer --output $INDEXNAME.rvtindexer.json --type data --searchBody "{\"query\":{\"term\":{\"name.keyword\": \"$INDEXNAME\"}}}"
