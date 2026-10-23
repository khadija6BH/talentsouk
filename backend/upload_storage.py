"""Private Supabase object storage with a disposable local file cache.

Only paths under STORAGE_ROOT/uploads are remote. Lock/temp files stay local.
Existing owner-scoped Flask routes remain responsible for authorization.
"""
import json
import mimetypes
import os
from pathlib import Path
from urllib import request, error, parse


def enabled():
    return os.getenv('UPLOAD_STORAGE', 'local') == 'supabase'


def object_key(path):
    if not enabled():
        return None
    root = Path(os.getenv('STORAGE_ROOT', Path(__file__).resolve().parent.parent)).resolve() / 'uploads'
    try:
        relative = Path(path).resolve().relative_to(root)
    except ValueError:
        return None
    if not relative.parts or any(part.startswith('.') or part.endswith('.tmp') for part in relative.parts):
        return None
    return relative.as_posix()


def call(method, suffix, data=None, content_type='application/json', missing_ok=False):
    base = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_STORAGE_KEY', '')
    if not base.startswith('https://') or not key:
        raise OSError('Private upload storage is not configured.')
    headers = {'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': content_type,
               'x-upsert': 'true'}
    req = request.Request(base + '/storage/v1/' + suffix, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=45) as response:
            return response.read(16 * 1024 * 1024 + 1)
    except error.HTTPError as exc:
        # Storage returns 400 for Object not found as well as ordinary 404.
        raw = exc.read(8192)
        if missing_ok and (exc.code == 404 or (exc.code == 400 and b'not found' in raw.lower())):
            return None
        raise OSError('Private upload storage is unavailable (HTTP %s).' % exc.code) from None
    except (error.URLError, TimeoutError):
        raise OSError('Private upload storage could not be reached.') from None


def bucket():
    return parse.quote(os.getenv('SUPABASE_STORAGE_BUCKET', 'talentsouk-private'), safe='')


def object_url(key):
    return 'object/' + bucket() + '/' + parse.quote(key, safe='/')


def remote_list(prefix):
    result = []
    offset = 0
    while True:
        body = call('POST', 'object/list/' + bucket(), json.dumps(
            {'prefix': prefix.strip('/'), 'limit': 100, 'offset': offset, 'sortBy': {'column': 'name', 'order': 'asc'}}).encode())
        batch = json.loads(body)
        if not isinstance(batch, list):
            raise OSError('Private storage returned an invalid listing.')
        for item in batch:
            name = item.get('name', '')
            if name and '/' not in name and name not in {'.', '..'} and item.get('id'):
                result.append(name)
        if len(batch) < 100:
            return result
        offset += len(batch)


class UploadPath(type(Path())):
    """Path interface for legacy CV/portrait code; uploads persist before success."""
    def _cache(self):
        key = object_key(self)
        local = Path(self)
        if key and not local.is_file():
            data = call('GET', object_url(key), missing_ok=True)
            if data is not None:
                if len(data) > 16 * 1024 * 1024:
                    raise OSError('Stored file exceeds the allowed size.')
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
        return local

    def is_file(self):
        return self._cache().is_file()

    def exists(self):
        local = Path(self)
        if local.exists():
            return True
        key = object_key(self)
        if key and not self.suffix:
            if remote_list(key + '/'):
                local.mkdir(parents=True, exist_ok=True)
                return True
            return False
        return self._cache().exists()

    def read_bytes(self):
        return self._cache().read_bytes()

    def read_text(self, encoding=None, errors=None):
        return self.read_bytes().decode(encoding or 'utf-8', errors or 'strict')

    def write_bytes(self, data):
        key = object_key(self)
        if key:
            call('POST', object_url(key), data, mimetypes.guess_type(str(self))[0] or 'application/octet-stream')
        return Path(self).write_bytes(data)

    def write_text(self, data, encoding=None, errors=None, newline=None):
        if not object_key(self):
            return Path(self).write_text(data, encoding=encoding, errors=errors, newline=newline)
        self.write_bytes(data.encode(encoding or 'utf-8', errors or 'strict'))
        return len(data)

    def replace(self, target):
        target = UploadPath(target)
        key = object_key(target)
        if key:
            call('POST', object_url(key), Path(self).read_bytes(), mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
        Path(self).replace(Path(target))
        return target

    def unlink(self, missing_ok=False):
        key = object_key(self)
        if key:
            call('DELETE', 'object/' + bucket(), json.dumps({'prefixes': [key]}).encode())
        Path(self).unlink(missing_ok=missing_ok or bool(key))

    def glob(self, pattern):
        key = object_key(self)
        if key:
            from fnmatch import fnmatchcase
            names = remote_list(key + '/')
            for name in names:
                if fnmatchcase(name, pattern):
                    yield self / name
        else:
            yield from super().glob(pattern)


def delete_folder(path):
    key = object_key(path)
    if key:
        names = remote_list(key + '/')
        for offset in range(0, len(names), 100):
            call('DELETE', 'object/' + bucket(), json.dumps(
                {'prefixes': [key + '/' + name for name in names[offset:offset + 100]]}).encode())
