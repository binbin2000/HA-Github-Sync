"""Small admin-only Home Assistant ingress view for the scheduled runner."""
from contextlib import contextmanager
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
from threading import Event, Lock, Thread
from urllib.parse import parse_qs


class SyncRequests:
    def __init__(self):
        self.lock = Lock()
        self.wake = Event()
        self.stopping = False
        self.pending = False
        self.running = False
        self.next_run = None
        self.last_code = None

    def stop(self):
        # Called by a signal handler: do not take locks here. The scheduler
        # checks the flag at most five seconds later or after its active run.
        self.stopping = True

    def request(self):
        with self.lock:
            if self.stopping or self.pending or self.running:
                return False
            self.pending = True
            self.wake.set()
            return True

    def claim(self, *, due):
        with self.lock:
            if self.stopping or self.running or not (self.pending or due):
                return None
            source = 'manual' if self.pending else 'scheduled'
            self.pending = False
            self.running = True
            self.wake.clear()
            return source

    def finish(self, code):
        with self.lock:
            self.last_code = code
            self.running = False

    def set_next(self, when):
        with self.lock:
            self.next_run = when

    def status(self):
        with self.lock:
            return self.pending, self.running, self.next_run, self.last_code


class IngressHandler(BaseHTTPRequestHandler):
    supervisor_ip = '172.30.32.2'
    timeout = 5

    def log_message(self, *_):
        pass

    def trusted(self):
        if self.client_address[0] != self.supervisor_ip:
            self.send_error(403)
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        if self.path != '/':
            self.send_error(404)
            return
        pending, running, when, code = self.server.requests.status()
        busy = pending or running
        status = ('Syncing…' if running else 'Queued…' if pending else
                  'Ready' if code is None else 'Last sync succeeded' if code == 0 else
                  f'Last sync failed (exit {code}). See the app log.')
        refresh = '<meta http-equiv="refresh" content="3">' if busy else ''
        disabled = 'disabled' if busy or self.server.requests.stopping else ''
        page = f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{refresh}<title>HA GitHub Sync</title>
<style>
body {{ font: 16px system-ui, sans-serif; color-scheme: light dark; margin: 2rem auto; padding: 0 1rem; max-width: 34rem; }}
button {{ font: inherit; padding: .65rem 1rem; cursor: pointer; }}
</style>
<h1>HA GitHub Sync</h1>
<p role="status">{escape(status)}</p>
<p>Next scheduled sync: <strong>{escape(when or 'Calculating…')}</strong></p>
<form method="post" action="./sync">
  <input type="hidden" name="csrf" value="{self.server.csrf}">
  <button type="submit" {disabled}>Sync now</button>
</form></html>'''.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(page)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        if not self.trusted():
            return
        if self.path != '/sync':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 256 or self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                raise ValueError
            fields = parse_qs(self.rfile.read(length).decode('ascii'), max_num_fields=1)
        except (ValueError, TimeoutError):
            self.send_error(400)
            return
        values = fields.get('csrf', [])
        if len(values) != 1 or not values[0].isascii() or not secrets.compare_digest(values[0], self.server.csrf):
            self.send_error(403)
            return
        self.server.requests.request()
        # Relative redirect stays under the current Home Assistant ingress URL.
        self.send_response(303)
        self.send_header('Location', './')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()


@contextmanager
def serve_ui(requests, address=('0.0.0.0', 8099), handler=IngressHandler):
    with ThreadingHTTPServer(address, handler) as server:
        server.requests = requests
        server.csrf = secrets.token_urlsafe(32)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()
