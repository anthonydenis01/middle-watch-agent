"""Bound requests before parsing; rate-limit one worker without retaining raw IPs."""
from collections import deque
import hashlib
from ipaddress import ip_address, ip_network
import math
from threading import Lock
import time
from starlette.responses import JSONResponse
from api.config import FEED_NOTICE


def error_response(status, code, message, *, headers=None, issues=None):
    error = {'code': code, 'message': message}
    if issues is not None:
        error['issues'] = issues
    return JSONResponse(status_code=status, headers=headers, content={
        'detail': message, 'error': error, 'feed_notice': FEED_NOTICE})


class RunLimiter:
    def __init__(self, limit, clock=time.monotonic, capacity=10000):
        self.limit, self.clock, self.capacity = limit, clock, capacity
        self.buckets = {}
        self.lock = Lock()

    def allow(self, address):
        stamp = self.clock()
        key = hashlib.sha256(address.encode()).digest()
        with self.lock:
            for old in list(self.buckets):
                queue = self.buckets[old]
                while queue and queue[0] <= stamp - 3600:
                    queue.popleft()
                if not queue:
                    del self.buckets[old]
            if key not in self.buckets and len(self.buckets) >= self.capacity:
                return 60
            queue = self.buckets.setdefault(key, deque())
            if len(queue) >= self.limit:
                return max(1, math.ceil(3600 - (stamp - queue[0])))
            queue.append(stamp)
            return 0


def client_address(scope, render_proxy=False):
    peer = (scope.get('client') or ('unknown', 0))[0]
    if render_proxy:
        try:
            address = ip_address(peer)
            # Only trust Render's edge-injected single-IP header via its private proxy.
            networks = ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1/128', 'fc00::/7')
            headers = [value for key, value in scope['headers'] if key.lower() == b'true-client-ip']
            if any(address in ip_network(network) for network in networks) and len(headers) == 1:
                return str(ip_address(headers[0].decode('ascii')))
        except (ValueError, UnicodeError):
            pass
    return peer


class RequestGuard:
    def __init__(self, app, limiter, render_proxy=False):
        self.app, self.limiter, self.render_proxy = app, limiter, render_proxy

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope['path'], scope['method']
        if method == 'POST' and (path.rstrip('/') in (
                '/api/watchlists', '/api/watchlists/csv', '/api/watchlists/sample', '/api/benchmark')):
            retry = self.limiter.allow(client_address(scope, self.render_proxy))
            if retry:
                return await error_response(429, 'rate_limited', 'Run limit reached. Please try again later.',
                    headers={'Retry-After': str(retry)})(scope, receive, send)
        # Buffer at most the cap, including bodies without Content-Length.
        cap = 210000 if path.rstrip('/') == '/api/watchlists/csv' else 16000
        headers = dict(scope['headers'])
        try:
            length = int(headers.get(b'content-length', b'0'))
            if length < 0:
                raise ValueError
        except ValueError:
            return await error_response(400, 'invalid_length', 'Invalid request length.')(scope, receive, send)
        if length > cap:
            return await error_response(413, 'body_too_large', 'Request body exceeds the size limit.')(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > cap:
                return await error_response(413, 'body_too_large', 'Request body exceeds the size limit.')(scope, receive, send)
            if not message.get('more_body', False):
                break
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)
