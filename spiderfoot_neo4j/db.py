import re
import sys
import tld
import time
import py2neo
import hashlib
import logging
import sqlite3
from collections import OrderedDict

logging.getLogger('py2neo').setLevel(logging.WARNING)


class Neo4jDb:
    '''Neo4j graph database'''

    # used for cleaning/validating neo4j labels
    sanitary_regex = re.compile(r'\w+')

    def __init__(self, sqlitedb, uri='bolt://localhost:7687', username='neo4j', password='spiderfoot'):
        self.log = logging.getLogger('sfgraph.neo4j')

        # set up sqlite database
        self.sqlitedb = str(sqlitedb)
        self._sqlite = None

        # set up Neo4j database
        self.uri = str(uri)
        self.username = str(username)
        self.password = str(password)
        try:
            self.log.debug(f'Connecting to {self.uri} with username {self.username}')
            self._graph = py2neo.Graph(uri=self.uri, auth=(self.username, self.password))
        except py2neo.errors.ConnectionUnavailable as e:
            raise IOError(f'Error connecting to Neo4j database {self.uri}: {e}')

        self.uniquenessConstraints = set()

    def clear(self):
        # delete relationships
        self._graph.run('MATCH (a)-[r]->() DELETE a, r')
        # delete nodes
        self._graph.run('MATCH (a) DELETE a')
        self.log.info(f'Successfully cleared database at {self.uri}')

    @property
    def sqlite(self):
        if self._sqlite is None:
            self._sqlite = sqlite3.connect(self.sqlitedb)
            self._sqlite.row_factory = self._dictFactory
        return self._sqlite

    def importScan(self, scanId):
        counter = 0
        events = {}
        for event in self.runSql(
            'SELECT * FROM tbl_scan_results WHERE scan_instance_id = :scan_instance_id',
            {'scan_instance_id': scanId}
        ):
            events[event['hash']] = event

        # break into batches for better performance
        batches = []
        batch_size = 1000

        graph = None
        for i,event in enumerate(events.values()):
            try:
                sourceEvent = events[event['source_event_hash']]
                moduleType = self._sanitizeString(event.get('module', '').split('sfp_')[-1]).upper()
                subgraph = self.makeSubgraph(event, sourceEvent)
                if graph is not None:
                    graph = graph | subgraph
                else:
                    graph = subgraph
                if i % batch_size == 0:
                    batches.append(graph)
                    graph = None
                counter += 1
                sys.stdout.write(f'\r[+] Imported {counter:,} events from scan {scanId}')
            except Exception as e:
                print(f'\nError importing event: {event}. Please report this is a bug.\n')
        if graph:
            batches.append(graph)

        if batches:
            graph = batches[0]
            for g in batches[:-1]:
                graph = graph | g

        print('')
        self._graph.merge(graph)
        return counter

    def makeSubgraph(self, event, sourceEvent):
        moduleType = self._sanitizeString(event.get('module', '').split('sfp_')[-1]).upper()
        event = self.makeEventNode(event)
        sourceEvent = self.makeEventNode(sourceEvent)

        # relationship
        if not moduleType:
            moduleType = 'NONE'

        subgraph = py2neo.Relationship(sourceEvent, moduleType, event)

        # if event is associated with a domain, create additional relationships
        if any([event.has_label(l) for l in ('INTERNET_NAME', 'EMAILADDR')]):
            subgraph = subgraph | self.makeDomainNode(event)
        return subgraph

    def run(self, *args, **kwargs):
        return self._graph.run(*args, **kwargs).data()

    def runSql(self, *args, **kwargs):
        cur = self.sqlite.cursor()
        return cur.execute(*args, **kwargs)

    def projectAll(self):
        try:
            self.run('''CALL gds.graph.drop('everything')''')
        except py2neo.errors.ClientError:
            pass
        return self.run('''
            CALL gds.graph.create('everything','*', '*')
            YIELD graphName, nodeCount, relationshipCount''')

    def pageRank(self):
        self.projectAll()
        for r in self.run('''
            CALL gds.pageRank.stream('everything')
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId) AS n, score
            ORDER BY score DESC'''):
            if r['n'] and r['score']:
                yield (r['n'], r['score'])

    def articleRank(self):
        self.projectAll()
        for r in self.run('''
            CALL gds.pageRank.stream('everything')
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId) AS n, score
            ORDER BY score DESC'''):
            if r['n'] and r['score']:
                yield (r['n'], r['score'])

    def closenessCentrality(self):
        self.projectAll()
        for r in self.run('''
            CALL gds.alpha.closeness.stream('everything')
            YIELD nodeId, centrality
            RETURN gds.util.asNode(nodeId) AS n, centrality
            ORDER BY centrality DESC'''):
            if r['n'] and r['centrality']:
                yield (r['n'], r['centrality'])

    def harmonicCentrality(self):
        self.projectAll()
        for r in self.run('''
            CALL gds.alpha.closeness.harmonic.stream('everything')
            YIELD nodeId, centrality
            RETURN gds.util.asNode(nodeId) AS n, centrality
            ORDER BY centrality DESC'''):
            if r['n'] and r['centrality']:
                yield (r['n'], r['centrality'])

    def betweennessCentrality(self):
        self.projectAll()
        for r in self.run('''
            CALL gds.betweenness.stream('everything')
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId) AS n, score
            ORDER BY score DESC'''):
            if r['n'] and r['score']:
                yield (r['n'], r['score'])

    def eigenvectorCentrality(self):
        self.projectAll()
        for r in self.run('''
            CALL gds.eigenvector.stream('everything')
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId) AS n, score
            ORDER BY score DESC'''):
            if r['n'] and r['score']:
                yield (r['n'], r['score'])

    def makeEventNode(self, event):
        storeData = str(event.get('data', ''))
        # hash only the data so that nodes with matching type and data are merged
        eventHash = self.hashstring(storeData)

        affiliate = False
        scanned = False
        # 'affiliate' label is stripped off and stored as attribute
        if event['type'].startswith('AFFILIATE_'):
            eventType = self._sanitizeString(event['type'].split('AFFILIATE_', 1))
        else:
            eventType = self._sanitizeString(event['type'])
        if 'AFFILIATE_' in event['type'] or event.get('affiliate', False):
            affiliate = True
        else:
            scanned = True

        # lowercase certain data types
        if any([x in eventType for x in ('INTERNET_NAME', 'DOMAIN_NAME', 'EMAILADDR')]):
            storeData = storeData.lower()

        # create uniqueness constraints (also creates indexes)
        if not eventType in self.uniquenessConstraints:
            try:
                self._graph.schema.create_uniqueness_constraint(eventType, 'hash')
            except py2neo.errors.ClientError:
                # constraint already exists
                pass
            self.uniquenessConstraints.add(eventType)

        nodeData = {
            'data': storeData,
            'hash': eventHash,
            'confidence': event.get('confidence', 100),
            'visibility': event.get('visibility', 100),
            'risk': event.get('risk', 0),
            'generated': event.get('generated', round(time.time(), 5))
        }

        if affiliate:
            nodeData['affiliate'] = True
        if scanned:
            nodeData['scanned'] = True

        # event node
        eventNode = py2neo.Node(
            eventType,
            **nodeData
        )
        eventNode.__primarylabel__ = eventType
        eventNode.__primarykey__ = 'hash'
        return eventNode

    def makeDomainNode(self, sourceNode, child=None):
        data = sourceNode.get('data', '').strip().lower()
        label = list(sourceNode.labels)[0]
        host = data.split('@')[-1].strip()
        parentDomain = host.split('.', 1)[-1]

        if label == 'EMAILADDR':
            parentData = host
            parentType = 'INTERNET_NAME'
        else:
            if tld.is_tld(parentDomain):
                parentData = host
                parentType = 'DOMAIN_NAME'
            else:
                parentData = parentDomain
                parentType = 'INTERNET_NAME'

        nodeData = {
            'data': parentData,
            'type': parentType,
        }
        affiliate = sourceNode.get('affiliate', False)
        scanned = sourceNode.get('scanned', False)
        if affiliate:
            nodeData['affiliate'] = True
        if scanned:
            nodeData['scanned'] = True

        parentNode = self.makeEventNode(nodeData)
        subgraph = py2neo.Relationship(sourceNode, 'PARENT_DOMAIN', parentNode)

        if parentType != 'DOMAIN_NAME':
            subgraph = subgraph | self.makeDomainNode(parentNode)

        return subgraph

    def _sanitizeString(self, s):
        return ''.join(self.sanitary_regex.findall('_'.join(str(s).split())))

    @staticmethod
    def _dictFactory(cursor, row):
        return OrderedDict([(col[0], row[idx]) for idx,col in enumerate(cursor.description)])

    @staticmethod
    def hashstring(s):
        return hashlib.sha256(str(s).encode('raw_unicode_escape')).hexdigest()