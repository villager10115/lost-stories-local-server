"""Serve preserved on-demand media using the client's FileDataRecord contract."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit


class RawMediaStore:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.records = {}
        for record in json.loads((self.root / 'filelist.json').read_text('utf8'))['Records']:
            path = record['Path']
            if (not re.fullmatch(r'(Movie|Sound)/[A-Za-z0-9_ ./-]+', path)
                    or any(p in ('', '.', '..') for p in path.split('/'))
                    or record['Type'] != 2 or type(record['Size']) is not int
                    or record['Size'] <= 0
                    or not re.fullmatch(r'[A-Fa-f0-9]{40}', record['Hash'])
                    or not isinstance(record['Labels'], list)):
                raise ValueError('Invalid media record')
            if path in self.records and self.records[path] != record:
                raise ValueError('Conflicting media records')
            self.records[path] = record
        self.filelist = json.dumps({'Records': list(self.records.values())},
                                   separators=(',', ':')).encode('utf8')

    def resolve(self, target):
        try:
            url = urlsplit(target)
            pairs = parse_qsl(url.query, keep_blank_values=True, max_num_fields=8)
        except ValueError:
            return 400, b'Invalid media target', 'text/plain'
        if (url.scheme or url.netloc or url.fragment
                or re.search(r'%(?!20)', url.path, re.I) or '\\' in target
                or any(p in ('.', '..') for p in url.path.split('/'))):
            return 400, b'Invalid media target', 'text/plain'
        path_text = unquote(url.path)
        if path_text == '/assets/filelist.json':
            # NoCacheDataFileProvider may append its time/rand cache busters.
            return 200, self.filelist, 'application/json'
        record = self.records.get(path_text.removeprefix('/assets/'))
        if not path_text.startswith('/assets/') or record is None:
            return 404, b'Media is not preserved', 'text/plain'
        hashes = [v for k, v in pairs if k == 'hash']
        if len(hashes) > 1 or (hashes and hashes[0] != record['Hash']):
            return 409, b'Media hash does not match preserved version', 'text/plain'
        try:
            path = (self.root / record['Path']).resolve(strict=True)
            if self.root not in path.parents or path.stat().st_size != record['Size']:
                return 503, b'Media file does not match manifest', 'text/plain'
            body = path.read_bytes()
        except OSError:
            return 503, b'Media file unavailable', 'text/plain'
        if hashlib.sha1(body).hexdigest().upper() != record['Hash'].upper():
            return 503, b'Media checksum mismatch', 'text/plain'
        return 200, body, 'application/octet-stream'
