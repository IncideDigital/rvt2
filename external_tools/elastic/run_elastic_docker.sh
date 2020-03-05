#!/bin/bash
TAG=7.4.2
DATA_DIR=$(pwd)/data
if [ ! -e "$DATA_DIR" ]; then
    mkdir -p "$DATA_DIR"
    chmod 777 "$DATA_DIR"
fi
docker run --rm -d --name elasticsearch \
    -v $DATA_DIR:/usr/share/elasticsearch/data \
    -v $(pwd)/elasticsearch.yml:/usr/share/elasticsearch/config/elasticsearch.yml \
    -p 9200:9200 -p 9300:9300 \
    elasticsearch:$TAG
