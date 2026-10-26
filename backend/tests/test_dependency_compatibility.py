"""Offline compatibility checks for the cache's FileLock API, not read-write lock protocols."""

import subprocess
import sys

import requests
import tldextract
from filelock import FileLock
from tldextract import suffix_list


def test_tldextract_cache_cold_hot_and_new_instance_are_offline(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError('suffix cache compatibility must not use the network')

    monkeypatch.setattr(requests.Session, 'request', no_network)
    cache_dir = tmp_path / 'suffix-cache'
    assert not cache_dir.exists()
    extractor = tldextract.TLDExtract(cache_dir=str(cache_dir), suffix_list_urls=())
    cold = extractor('https://tenders.example.co.uk/notice')
    assert (cold.subdomain, cold.domain, cold.suffix) == ('tenders', 'example', 'co.uk')
    cache_files = {path: path.read_bytes() for path in cache_dir.rglob('*.tldextract.json')}
    assert cache_files

    def cache_miss(*_args, **_kwargs):
        raise AssertionError('warm cache must not rebuild the suffix lists')

    monkeypatch.setattr(suffix_list, '_get_suffix_lists', cache_miss)
    hot = extractor('https://procurement.example.co.uk/notice')
    assert (hot.subdomain, hot.domain, hot.suffix) == ('procurement', 'example', 'co.uk')
    reopened = tldextract.TLDExtract(cache_dir=str(cache_dir), suffix_list_urls=())
    cached = reopened('https://notice.example.org/item')
    assert (cached.subdomain, cached.domain, cached.suffix) == ('notice', 'example', 'org')
    assert {path: path.read_bytes() for path in cache_dir.rglob('*.tldextract.json')} == cache_files


def test_filelock_excludes_a_process_then_allows_reacquisition(tmp_path):
    lock_path = tmp_path / 'cache.lock'
    probe_source = '''
import sys
from filelock import FileLock, Timeout
try:
    with FileLock(sys.argv[1], timeout=0.2):
        print('acquired')
except Timeout:
    print('contended')
'''

    def probe():
        return subprocess.run(
            [sys.executable, '-c', probe_source, str(lock_path)],
            cwd=tmp_path, capture_output=True, text=True, timeout=5, check=True,
        )

    lock = FileLock(lock_path, timeout=1)
    with lock:
        assert lock.is_locked
        assert probe().stdout.strip() == 'contended'
    assert not lock.is_locked
    assert probe().stdout.strip() == 'acquired'
