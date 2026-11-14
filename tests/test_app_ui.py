import http.client
import re
import unittest
from urllib.parse import urlencode

from app_ui import IngressHandler, SyncRequests, serve_ui


class LocalIngress(IngressHandler):
    supervisor_ip = '127.0.0.1'


class SyncButtonTests(unittest.TestCase):
    def request(self, server, method, path, body=None):
        conn = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            headers = {'Content-Type': 'application/x-www-form-urlencoded'} if body else {}
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheader('Location'), response.read().decode()
        finally:
            conn.close()

    def test_button_queues_one_run_and_shows_result(self):
        requests = SyncRequests()
        with serve_ui(requests, ('127.0.0.1', 0), LocalIngress) as server:
            status, _, page = self.request(server, 'GET', '/')
            self.assertEqual(status, 200)
            self.assertIsNone(requests.claim(due=False))
            token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            body = urlencode({'csrf': token})
            self.assertEqual(self.request(server, 'POST', '/sync', body)[:2], (303, './'))
            self.assertEqual(self.request(server, 'POST', '/sync', body)[0], 303)
            self.assertEqual(requests.claim(due=True), 'manual')
            self.assertIn('disabled>Sync now', self.request(server, 'GET', '/')[2])
            self.request(server, 'POST', '/sync', body)
            self.assertIsNone(requests.claim(due=True))
            requests.finish(0)
            self.assertIsNone(requests.claim(due=False))
            self.assertIn('Last sync succeeded', self.request(server, 'GET', '/')[2])

    def test_invalid_form_and_non_ingress_client_cannot_queue(self):
        requests = SyncRequests()
        with serve_ui(requests, ('127.0.0.1', 0), LocalIngress) as server:
            self.assertEqual(self.request(server, 'POST', '/sync', 'csrf=wrong')[0], 403)
            self.assertEqual(self.request(server, 'GET', '/sync')[0], 404)
        with serve_ui(requests, ('127.0.0.1', 0)) as server:
            self.assertEqual(self.request(server, 'GET', '/')[0], 403)
            body = urlencode({'csrf': server.csrf})
            self.assertEqual(self.request(server, 'POST', '/sync', body)[0], 403)
        self.assertIsNone(requests.claim(due=False))
