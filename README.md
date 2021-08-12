# Spiderfoot Neo4j Tools
Import, visualize, and analyze SpiderFoot scans in Neo4j, a graph database

![Spiderfoot data in Neo4j](https://user-images.githubusercontent.com/20261699/129260731-5a2c85d6-fa5a-40b0-a37f-b008c7948a8e.png)

### Step 1: Installation
NOTE: This installs the `sfgraph` command-line utility
~~~
$ pip install spiderfoot-neo4j
~~~
### Step 2: Start Neo4j
NOTE: [Docker must first be installed](https://docs.docker.com/get-docker/)
~~~
$ docker run --rm --name sfgraph -v "$(pwd)/neo4j_database:/data" -e 'NEO4J_AUTH=neo4j/CHANGETHISIFYOURENOTZUCK' -e 'NEO4JLABS_PLUGINS=["apoc", "graph-data-science"]' -e 'NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.*' -p "7474:7474" -p "7687:7687" neo4j
~~~
### Step 3: Import Scans

![Spiderfoot scan ID in web browser](https://user-images.githubusercontent.com/20261699/129256011-ff751637-afdd-4632-8335-24ffae2ff65e.png)
~~~
$ sfgraph path_to/spiderfoot.db -s <SCANID_1> <SCANID_2> ...
~~~

### Step 4: Browse Spiderfoot Data in Neo4j
Visit http://127.0.0.1:7474 and log in with `neo4j/CHANGETHISIFYOURENOTZUCK`

### Step 5 (Optional): Use cool algorithms to find new targets
The `--suggest` option will rank nodes based on their connectedness in the graph. This is perfect for finding closely-related affiliates (child companies, etc.) to scan and add to the graph. By default, [Harmonic Centrality](https://neo4j.com/docs/graph-data-science/current/algorithms/harmonic-centrality/) is used, but others such as [PageRank](https://neo4j.com/docs/graph-data-science/current/algorithms/page-rank/) can be specified with `--closeness-algorithm`
~~~
$ sfgraph --suggest DOMAIN_NAME
~~~

![Closeness scores](https://user-images.githubusercontent.com/20261699/129263951-977d1092-8fdd-4ea1-bccb-d1ab6e4a6612.png)

## Example CYPHER Queries
~~~
# match all INTERNET_NAMEs
MATCH (n:INTERNET_NAME) RETURN n

# match multiple event types
MATCH (n) WHERE n:INTERNET_NAME OR n:DOMAIN_NAME OR n:EMAILADDR RETURN n

# match by attribute
MATCH (n {data: "evilcorp.com"}) RETURN n

# match by spiderfoot module (relationship)
MATCH p=()-[r:WHOIS]->() RETURN p

# shortest path to all INTERNET_NAMEs from seed domain
MATCH p=shortestPath((d:DOMAIN_NAME {data:"evilcorp.com"})-[*]-(n:INTERNET_NAME)) RETURN p

# match only primary targets (non-affiliates)
MATCH (n {scanned: true}) return n

# match only affiliates
MATCH (n {affiliate: true}) return n
~~~

## CLI Help
~~~
sfgraph [-h] [-db SQLITEDB] [-s SCANS [SCANS ...]] [--uri URI] [-u USERNAME] [-p PASSWORD] [--clear] [--suggest SUGGEST]
               [--closeness-algorithm {pageRank,articleRank,closenessCentrality,harmonicCentrality,betweennessCentrality,eigenvectorCentrality}] [-v]

optional arguments:
  -h, --help            show this help message and exit
  -db SQLITEDB, --sqlitedb SQLITEDB
                        Spiderfoot sqlite database
  -s SCANS [SCANS ...], --scans SCANS [SCANS ...]
                        scan IDs to import
  --uri URI             Neo4j database URI (default: bolt://127.0.0.1:7687)
  -u USERNAME, --username USERNAME
                        Neo4j username (default: neo4j)
  -p PASSWORD, --password PASSWORD
                        Neo4j password
  --clear               Wipe the Neo4j database
  --suggest SUGGEST     Suggest targets of this type (e.g. DOMAIN_NAME) based on their connectedness in the graph
  --closeness-algorithm {pageRank,articleRank,closenessCentrality,harmonicCentrality,betweennessCentrality,eigenvectorCentrality}
                        Algorithm to use when suggesting targets
  -v, -d, --debug       Verbose / debug
~~~