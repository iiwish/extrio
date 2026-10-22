import argparse
import hashlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx


class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def relay(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length) if length else b''
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in {'host', 'connection', 'content-length', 'accept-encoding'}}
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.request(self.command, self.server.upstream + self.path, headers=headers, content=body)
        drop = False
        if self.command == 'POST' and self.path == '/api/v1/collectors/batch':
            payload = response.json()
            with self.server.event_lock:
                drop = not self.server.dropped and response.status_code == 200 and payload.get('createdCount', 0) > 0
                if drop:
                    self.server.dropped = True
                event = {
                    'method': self.command, 'path': self.path, 'status': response.status_code,
                    'keyHash': hashlib.sha256(self.headers.get('Idempotency-Key', '').encode()).hexdigest(),
                    'bodyHash': hashlib.sha256(body).hexdigest(),
                    'createdCount': payload.get('createdCount'), 'rejectedCount': payload.get('rejectedCount'),
                    'collectionId': payload.get('collectionId'),
                    'collectorIds': [item['collector']['id'] for item in payload.get('results', []) if item.get('collector')],
                    'replayed': response.headers.get('Idempotency-Replayed') == 'true', 'droppedAfterCommit': drop,
                }
                with self.server.events.open('a') as handle:
                    handle.write(json.dumps(event) + '\n')
        if drop:
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.send_response(response.status_code)
        for key, value in response.headers.multi_items():
            if key.lower() not in {'content-length', 'content-encoding', 'transfer-encoding', 'connection'}:
                self.send_header(key, value)
        self.send_header('Content-Length', str(len(response.content)))
        self.end_headers()
        self.wfile.write(response.content)

    do_GET = relay
    do_POST = relay
    do_PUT = relay
    do_PATCH = relay
    do_DELETE = relay

    def log_message(self, *_):
        pass


parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--upstream', required=True)
parser.add_argument('--events', type=Path, required=True)
args = parser.parse_args()
assert args.upstream == 'http://127.0.0.1:8056'
assert args.events.parent == Path('/tmp/extrio-p2-qa')
server = ThreadingHTTPServer(('127.0.0.1', args.port), Proxy)
server.upstream, server.events = args.upstream, args.events
server.event_lock, server.dropped = threading.Lock(), False
print(json.dumps({'port': args.port, 'upstream': args.upstream, 'purpose': 'drop one batch response after commit'}), flush=True)
server.serve_forever()
