"""Minimal HTTP server with Range request support (needed for <video> playback)."""
import http.server
import os

class RangeHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().send_head()

        file_size = os.path.getsize(path)
        range_header = self.headers.get('Range')

        if range_header:
            # Parse "bytes=start-end"
            range_spec = range_header.replace('bytes=', '')
            parts = range_spec.split('-')
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            self.send_response(206)
            ctype = self.guess_type(path)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
            self.send_header('Content-Length', str(length))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()

            f = open(path, 'rb')
            f.seek(start)
            return _RangeFile(f, length)
        else:
            self.send_response(200)
            ctype = self.guess_type(path)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            return open(path, 'rb')

class _RangeFile:
    """Wrapper that reads only `length` bytes from a file object."""
    def __init__(self, f, length):
        self.f = f
        self.remaining = length
    def read(self, n=-1):
        if self.remaining <= 0:
            return b''
        if n < 0:
            n = self.remaining
        data = self.f.read(min(n, self.remaining))
        self.remaining -= len(data)
        return data
    def close(self):
        self.f.close()

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    server = http.server.HTTPServer(('', port), RangeHTTPRequestHandler)
    print(f'Serving on http://localhost:{port} (with Range support)')
    server.serve_forever()
