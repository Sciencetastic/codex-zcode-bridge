"""Authenticated local adapter client. Reads a JSON request array from stdin."""
import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--connection', required=True, help='Private runtime connection.json')
args = parser.parse_args()
connection = json.loads(Path(args.connection).read_text())
port = connection['port']
if type(port) is not int or not 1 <= port <= 65535:
    parser.error('Invalid local port')
for body in json.load(sys.stdin):
    request = urllib.request.Request(f'http://127.0.0.1:{port}/rpc',
        data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + connection['token']})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(json.dumps(json.loads(response.read())), flush=True)
    except urllib.error.HTTPError as error:
        print(json.dumps(json.loads(error.read())), flush=True)
