#!/usr/bin/env python3

import sys
import logging
import argparse
from pathlib import Path

# fscking imports amirite
package_path = Path(__file__).resolve().parent
sys.path.append(str(package_path))
from db import Neo4jDb

log = logging.getLogger('sfgraph')
log.setLevel(logging.INFO)
log_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

console_handler = logging.StreamHandler(sys.stderr)
console_handler.setFormatter(log_format)
log.addHandler(console_handler)


def main(options):

    neo4j = Neo4jDb(
        options.sqlitedb,
        uri=options.uri,
        username=options.username,
        password=options.password
    )

    if options.clear:
        neo4j.clear()

    total_events = 0
    for scan_instance_id in options.scans:
        total_events += neo4j.importScan(str(scan_instance_id).upper())
    if len(options.scans) > 1:
        print(f'[+] Imported {total_events:,} total events')

    suggestions = dict()
    if options.suggest:
        log.info(f'Computing {options.closeness_algorithm}\n')
        alg_fn = getattr(neo4j, options.closeness_algorithm)
        for node,score in alg_fn():
            if node.has_label(options.suggest):
                already_scanned = 'No'
                data = node.get('data', '')
                if node.get('scanned', False):
                    already_scanned = 'Yes'
                suggestion = {
                    'Data': data,
                    'Score': score,
                    'Scanned': already_scanned
                }
                if data:
                    try:
                        suggestions[data].update(suggestion)
                    except KeyError:
                        suggestions[data] = suggestion

        suggestions = sorted(list(suggestions.items()), key=lambda x: x[-1]['Score'], reverse=True)
        max_data_len = max([len(d[-1]['Data']) for d in suggestions])
        row_format = row_format = '{}{:<12}{:<12}'
        print(row_format.format(*['Data'.ljust(max_data_len) + '  ', 'Scanned', 'Score']))
        print('-' * (max_data_len + 20))
        for k,v in suggestions:
            k = k.ljust(max_data_len) + '  '
            values = []
            try:
                values.append(f'{v["Score"]:.4f}')
            except KeyError:
                values.append('')
            row = [k, v['Scanned']] + values
            print(row_format.format(*row))


def go():

    parser = argparse.ArgumentParser(description='')
    parser.add_argument('-db', '--sqlitedb', default='', help='Spiderfoot sqlite database')
    parser.add_argument('-s', '--scans', nargs='+', default=[], help='scan IDs to import')
    parser.add_argument('--uri', default='bolt://127.0.0.1:7687', help='Neo4j database URI (default: bolt://127.0.0.1:7687)')
    parser.add_argument('-u', '--username', default='neo4j', help='Neo4j username (default: neo4j)')
    parser.add_argument('-p', '--password', default='CHANGETHISIFYOURENOTZUCK', help='Neo4j password')
    parser.add_argument('--clear', action='store_true', help='Wipe the Neo4j database')
    parser.add_argument('--suggest', default='', help='Suggest targets of this type (e.g. DOMAIN_NAME) based on their connectedness in the graph')
    parser.add_argument('--closeness-algorithm', default='harmonicCentrality', choices=['pageRank', 'articleRank', 'closenessCentrality', 'harmonicCentrality', 'betweennessCentrality', 'eigenvectorCentrality'], help='Algorithm to use when suggesting targets')
    parser.add_argument('-v', '-d', '--debug', action='store_true', help='Verbose / debug')

    syntax_error = False
    try:

        if len(sys.argv) == 1:
            parser.print_help()
            sys.exit(1)

        options = parser.parse_args()
        options.suggest = options.suggest.upper().split('AFFILIATE_', 1)[-1]

        assert not (options.scans and not options.sqlitedb), 'Please specify path to SpiderFoot database with --sqlitedb'
        if options.scans:
            assert Path(str(options.sqlitedb)).is_file(), f'Unable to access sqlite database: {options.sqlitedb}'

        if options.debug:
            log.setLevel(logging.DEBUG)

        main(options)

    except argparse.ArgumentError as e:
        log.error(str(e))
        log.error('Check your syntax')
        sys.exit(2)

    except AssertionError as e:
        log.error(str(e))
        sys.exit(2)

    except KeyboardInterrupt:
        log.error('Interrupted')
        sys.exit(1)

    except BrokenPipeError:
        pass

if __name__ == '__main__':
    go()