"""Pluggable AI cache storage — local disk (default) or S3 object storage."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class CacheStorage(Protocol):
    def read(self, key: str) -> dict | None: ...
    def write(self, key: str, entry: dict) -> None: ...
    def delete(self, key: str) -> bool: ...
    def list_keys(self) -> list[str]: ...
    def describe(self) -> dict: ...


class DiskCacheStorage:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f'{key}.json')

    def read(self, key: str) -> dict | None:
        path = self._path(key)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def write(self, key: str, entry: dict) -> None:
        path = self._path(key)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(entry, f)

    def delete(self, key: str) -> bool:
        path = self._path(key)
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def list_keys(self) -> list[str]:
        out = []
        for fname in os.listdir(self.cache_dir):
            if fname.endswith('.json'):
                out.append(fname[:-5])
        return out

    def describe(self) -> dict:
        return {'backend': 'disk', 'path': self.cache_dir}


class S3CacheStorage:
    def __init__(self, *, bucket: str, prefix: str, region: str | None = None):
        import boto3

        self.bucket = bucket
        self.prefix = prefix.rstrip('/') + '/'
        self.client = boto3.client('s3', region_name=region or os.getenv('AWS_REGION'))

    def _key(self, key: str) -> str:
        return f'{self.prefix}{key}.json'

    def read(self, key: str) -> dict | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            return json.loads(obj['Body'].read().decode('utf-8'))
        except Exception as exc:
            try:
                from botocore.exceptions import ClientError

                if isinstance(exc, ClientError):
                    code = exc.response.get('Error', {}).get('Code', '')
                    if code in ('NoSuchKey', '404', 'NotFound'):
                        return None
            except ImportError:
                pass
            logger.debug('[ai_cache_s3] read %s: %s', key, exc)
            return None

    def write(self, key: str, entry: dict) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=json.dumps(entry).encode('utf-8'),
            ContentType='application/json',
        )

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def list_keys(self) -> list[str]:
        keys = []
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for item in page.get('Contents') or []:
                k = item['Key']
                if k.endswith('.json'):
                    keys.append(k[len(self.prefix):-5])
        return keys

    def describe(self) -> dict:
        return {'backend': 's3', 'bucket': self.bucket, 'prefix': self.prefix}


_storage: CacheStorage | None = None


def get_cache_storage() -> CacheStorage:
    global _storage
    if _storage is not None:
        return _storage

    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'instance',
        'ai_cache',
    )
    bucket = (os.getenv('AI_CACHE_S3_BUCKET') or '').strip()
    if bucket:
        try:
            _storage = S3CacheStorage(
                bucket=bucket,
                prefix=os.getenv('AI_CACHE_S3_PREFIX', 'trainiq/ai-cache'),
            )
            return _storage
        except Exception as exc:
            logger.warning('[ai_cache] S3 backend failed, using disk: %s', exc)

    _storage = DiskCacheStorage(cache_dir)
    return _storage
