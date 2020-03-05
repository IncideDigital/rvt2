This plugin parses files using [Tika](https://tika.apache.org/index.html) and indexes documents in [ElasticSearch](https://www.elastic.co).

You can use this plugin:

- To parse all documents in a directory with Tika and index the results in Elastic. This is the main use of the classes in this plugin.
- To parse documents with Tika and do something else with the result. For example, show a document's metadata in the screen.
- To index the output of other RVT2 modules. For example, you can index the output of the PST parser.

## Running

If you use the Tika module, you must run Tika in server mode by running `run.sh` inside the `$RVT2_HOME/external_tools/tika` directory. The first time you run this command, it will download Tika.

If you use the ElasticSearch indexer, you'll need an ElasticSearch >=6 server somewhere in the network. In some cases, ElasticSearch might need a special file system configuration. Also, if you are planning to use the [rvt2-analyzer](../analyzer/), the ElasticSearch must allow CORS requests at least from the domain of the analyzer. An example script to run ElasticSearch can be found inside the directory `$RVT2_HOME/external_tools/elastic`.