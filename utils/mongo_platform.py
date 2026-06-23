"""MongoDB operations platform — indexes, tenant DBs, GridFS health (CEO module)."""

from __future__ import annotations



import logging

import os

from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Any



from utils.ops_constants import MONGO_PROVISION_WORKERS, MONGO_STORAGE_WARN_MB



logger = logging.getLogger(__name__)





def _index_keys(coll) -> set[str]:

    keys: set[str] = set()

    for idx in coll.list_indexes():

        for k in idx.get('key', {}):

            keys.add(k)

    return keys





def _collection_stats(db, name: str) -> dict[str, Any]:

    try:

        coll = db[name]

        count = coll.estimated_document_count()

    except Exception:

        return {'name': name, 'count': 0, 'exists': False, 'indexes': [], 'missing_indexes': []}

    indexes = []

    indexed_fields: set[str] = set()

    for idx in coll.list_indexes():

        keys = list(idx.get('key', {}).keys())

        indexes.append({'name': idx.get('name'), 'keys': keys})

        indexed_fields.update(keys)

    return {

        'name': name,

        'count': count,

        'exists': True,

        'indexes': indexes,

        'indexed_fields': sorted(indexed_fields),

    }





def _gridfs_stats(db) -> dict[str, Any]:

    stats = {'files': 0, 'chunks': 0, 'total_bytes': 0}

    try:

        if 'fs.files' in db.list_collection_names():

            stats['files'] = db['fs.files'].estimated_document_count()

            try:

                pipe = [{'$group': {'_id': None, 'bytes': {'$sum': '$length'}}}]

                agg = list(db['fs.files'].aggregate(pipe))

                if agg:

                    stats['total_bytes'] = int(agg[0].get('bytes') or 0)

            except Exception:

                pass

        if 'fs.chunks' in db.list_collection_names():

            stats['chunks'] = db['fs.chunks'].estimated_document_count()

    except Exception as exc:

        stats['error'] = str(exc)

    return stats





def _mongo_server_stats(client) -> dict[str, Any]:

    stats: dict[str, Any] = {}

    try:

        info = client.server_info()

        stats['version'] = info.get('version')

        stats['storage_engine'] = info.get('storageEngine', {}).get('name')

    except Exception as exc:

        stats['error'] = str(exc)

        return stats



    try:

        status = client.admin.command('serverStatus')

        conn = status.get('connections', {})

        stats['connections'] = {

            'current': conn.get('current'),

            'available': conn.get('available'),

            'total_created': conn.get('totalCreated'),

        }

        mem = status.get('wiredTiger', {}).get('cache', {}) or status.get('mem', {})

        if mem:

            stats['memory'] = {

                'resident_mb': round((mem.get('resident') or mem.get('bytes currently in the cache', 0)) / (1024 * 1024), 2)

                if mem.get('resident') or mem.get('bytes currently in the cache')

                else None,

            }

    except Exception as exc:

        stats['server_status_error'] = str(exc)



    try:

        total_bytes = 0

        for db_name in client.list_database_names():

            if db_name in ('admin', 'local', 'config'):

                continue

            try:

                db_stats = client[db_name].command('dbStats')

                total_bytes += int(db_stats.get('dataSize') or 0) + int(db_stats.get('indexSize') or 0)

            except Exception:

                continue

        stats['total_storage_bytes'] = total_bytes

        stats['total_storage_mb'] = round(total_bytes / (1024 * 1024), 2)

    except Exception as exc:

        stats['storage_error'] = str(exc)



    return stats





def collect_mongo_monitor_stats() -> dict[str, Any]:

    """Lightweight Mongo snapshot for the DB performance monitor."""

    from mongodb_operations import FILES_COLLECTION, PROFILE_PICTURES_COLLECTION, get_mongo_connection

    from utils.mongo_catalog import missing_indexes_for_db



    client, db, _ = get_mongo_connection()

    if client is None or db is None:

        return {'available': False, 'reason': 'unavailable'}



    try:

        client.admin.command('ping')

    except Exception as exc:

        return {'available': False, 'reason': str(exc)}



    server = _mongo_server_stats(client)

    collections = []

    for coll_name in (PROFILE_PICTURES_COLLECTION, FILES_COLLECTION):

        coll = db[coll_name]

        indexes = [

            {'name': idx.get('name'), 'keys': list(idx.get('key', {}).keys())}

            for idx in coll.list_indexes()

        ]

        missing = [

            m for m in missing_indexes_for_db(db)

            if m['collection'] == coll_name

        ]

        collections.append({

            'name': coll_name,

            'count': coll.estimated_document_count(),

            'indexes': indexes,

            'missing_indexes': [m['field'] for m in missing],

        })



    issues = []

    for coll in collections:

        for field_name in coll['missing_indexes']:

            issues.append({

                'severity': 'warning',

                'category': 'mongo_missing_index',

                'collection': coll['name'],

                'field': field_name,

                'message': f"MongoDB '{db.name}.{coll['name']}' missing index on '{field_name}'.",

            })



    storage_mb = server.get('total_storage_mb') or 0

    if storage_mb >= MONGO_STORAGE_WARN_MB:

        issues.append({

            'severity': 'warning',

            'category': 'mongo_storage',

            'message': (

                f'MongoDB total storage ~{storage_mb:.0f} MB '

                f'(warn threshold {MONGO_STORAGE_WARN_MB} MB). Review GridFS retention.'

            ),

        })



    return {

        'available': True,

        'database': db.name,

        'collections': collections,

        'server': server,

        'issues': issues,

    }





def collect_mongo_ops_status() -> dict[str, Any]:

    """Full MongoDB ops snapshot for CEO console."""

    from mongodb_operations import get_mongo_connection

    from utils.mongo_catalog import MONGO_COLLECTION_CATALOG, missing_indexes_for_db

    from utils.mongo_tenant import LEGACY_DB_NAME, tenant_db_name



    result: dict[str, Any] = {

        'available': False,

        'uri_host': os.getenv('MONGO_URI', 'mongodb://localhost:27017').split('@')[-1][:80],

        'legacy_db': LEGACY_DB_NAME,

        'tenant_prefix': os.getenv('MONGO_TENANT_DB_PREFIX', 'trainiq_t'),

        'issues': [],

        'databases': [],

        'server': {},

    }



    client, legacy_db, _ = get_mongo_connection()

    if client is None or legacy_db is None:

        result['reason'] = 'unavailable'

        result['issues'].append({

            'severity': 'critical',

            'message': 'MongoDB unreachable — course uploads and GridFS disabled.',

        })

        return result



    try:

        client.admin.command('ping')

        result['available'] = True

        result['server'] = _mongo_server_stats(client)

    except Exception as exc:

        result['reason'] = str(exc)

        return result



    storage_mb = result['server'].get('total_storage_mb') or 0

    if storage_mb >= MONGO_STORAGE_WARN_MB:

        result['issues'].append({

            'severity': 'warning',

            'message': f'MongoDB storage ~{storage_mb:.0f} MB — consider archival or tiering.',

        })



    legacy_entry = {

        'kind': 'legacy',

        'name': legacy_db.name,

        'tenant_id': None,

        'provisioned': True,

        'collections': [],

        'gridfs': _gridfs_stats(legacy_db),

        'missing_indexes': missing_indexes_for_db(legacy_db),

    }

    for spec in MONGO_COLLECTION_CATALOG:

        coll_info = _collection_stats(legacy_db, spec.name)

        coll_info['description'] = spec.description

        coll_info['required'] = spec.required

        legacy_entry['collections'].append(coll_info)

    result['databases'].append(legacy_entry)



    try:

        from models import Tenant



        for tenant in Tenant.query.order_by(Tenant.id.asc()).all():

            db_name = tenant_db_name(tenant.id)

            if db_name not in client.list_database_names():

                result['databases'].append({

                    'kind': 'tenant',

                    'name': db_name,

                    'tenant_id': tenant.id,

                    'tenant_name': tenant.name,

                    'provisioned': False,

                    'collections': [],

                    'gridfs': {'files': 0, 'chunks': 0, 'total_bytes': 0},

                    'missing_indexes': [{'collection': '*', 'field': '*', 'reason': 'Tenant DB not provisioned'}],

                })

                result['issues'].append({

                    'severity': 'warning',

                    'message': f"Tenant '{tenant.name}' (id={tenant.id}) has no MongoDB database '{db_name}'.",

                })

                continue



            tdb = client[db_name]

            tentry = {

                'kind': 'tenant',

                'name': db_name,

                'tenant_id': tenant.id,

                'tenant_name': tenant.name,

                'provisioned': True,

                'collections': [],

                'gridfs': _gridfs_stats(tdb),

                'missing_indexes': missing_indexes_for_db(tdb),

            }

            for spec in MONGO_COLLECTION_CATALOG:

                if spec.name.startswith('fs.'):

                    continue

                coll_info = _collection_stats(tdb, spec.name)

                coll_info['description'] = spec.description

                tentry['collections'].append(coll_info)

            result['databases'].append(tentry)

            for miss in tentry['missing_indexes']:

                result['issues'].append({

                    'severity': 'warning',

                    'message': f"{db_name}: missing index on {miss['collection']}.{miss['field']}",

                })

    except Exception as exc:

        logger.warning('Tenant mongo scan skipped: %s', exc)

        result['issues'].append({'severity': 'info', 'message': f'Tenant scan partial: {exc}'})



    if legacy_entry['missing_indexes']:

        for miss in legacy_entry['missing_indexes']:

            result['issues'].append({

                'severity': 'warning',

                'message': f"{legacy_db.name}: missing index on {miss['collection']}.{miss['field']}",

            })



    result['status'] = (

        'critical' if not result['available'] else

        'warning' if result['issues'] else

        'healthy'

    )

    result['database_count'] = len(result['databases'])

    result['tenant_db_count'] = sum(1 for d in result['databases'] if d.get('kind') == 'tenant')

    result['unprovisioned_tenants'] = sum(

        1 for d in result['databases'] if d.get('kind') == 'tenant' and not d.get('provisioned')

    )

    return result





def ensure_mongo_indexes_on_db(db) -> dict[str, int]:

    from utils.mongo_catalog import apply_catalog_indexes



    return apply_catalog_indexes(db)





def _provision_tenant_worker(tenant_id: int) -> tuple[int, bool, str]:

    from utils.mongo_tenant import provision_tenant_mongo



    try:

        provision_tenant_mongo(tenant_id)

        return tenant_id, True, ''

    except Exception as exc:

        return tenant_id, False, str(exc)





def bootstrap_mongo(*, provision_tenants: bool = True) -> dict[str, Any]:

    """Ensure legacy + all tenant MongoDB databases and indexes."""

    from mongodb_operations import initialize_mongodb, setup_collections

    from utils.mongo_catalog import apply_catalog_indexes



    steps: list[dict[str, Any]] = []

    client, legacy_db = initialize_mongodb()

    if legacy_db is None:

        return {

            'status': 'skipped',

            'steps': [{'step': 'mongo_connect', 'ok': False, 'message': 'MongoDB unavailable — skipped.'}],

        }



    try:

        idx_result = apply_catalog_indexes(legacy_db)

        setup_collections(legacy_db)

        steps.append({

            'step': 'legacy_indexes',

            'ok': idx_result.get('failed', 0) == 0,

            'message': (

                f"Indexes on {legacy_db.name}: {idx_result.get('applied', 0)} applied, "

                f"{idx_result.get('failed', 0)} failed."

            ),

            'detail': idx_result,

        })

    except Exception as exc:

        steps.append({'step': 'legacy_indexes', 'ok': False, 'message': str(exc)})



    provisioned = failed = 0

    if provision_tenants:

        try:

            from models import Tenant



            tenant_ids = [t.id for t in Tenant.query.all()]

            workers = min(MONGO_PROVISION_WORKERS, max(1, len(tenant_ids)))



            if tenant_ids and workers > 1:

                with ThreadPoolExecutor(max_workers=workers) as pool:

                    futures = {pool.submit(_provision_tenant_worker, tid): tid for tid in tenant_ids}

                    for fut in as_completed(futures):

                        _tid, ok, err = fut.result()

                        if ok:

                            provisioned += 1

                        else:

                            failed += 1

                            logger.warning('Mongo provision tenant %s: %s', _tid, err)

            else:

                for tid in tenant_ids:

                    _tid, ok, err = _provision_tenant_worker(tid)

                    if ok:

                        provisioned += 1

                    else:

                        failed += 1



            steps.append({

                'step': 'tenant_provision',

                'ok': failed == 0,

                'message': (

                    f'Provisioned {provisioned}/{len(tenant_ids)} tenant DB(s) '

                    f'({workers} workers), {failed} failed.'

                ),

                'provisioned': provisioned,

                'failed': failed,

                'workers': workers,

            })

        except Exception as exc:

            steps.append({'step': 'tenant_provision', 'ok': False, 'message': str(exc)})



    ok = all(s.get('ok', False) for s in steps)

    return {'status': 'success' if ok else 'partial', 'steps': steps}





def latest_mongo_summary() -> dict[str, Any] | None:

    try:

        snap = collect_mongo_ops_status()

        if not snap.get('available'):

            return {'status': 'unavailable', 'detail': snap.get('reason', 'unavailable')}

        return {

            'status': snap.get('status', 'unknown'),

            'database_count': snap.get('database_count', 0),

            'issue_count': len(snap.get('issues') or []),

            'legacy_db': snap.get('legacy_db'),

            'storage_mb': (snap.get('server') or {}).get('total_storage_mb'),

        }

    except Exception as exc:

        logger.debug('latest_mongo_summary skipped: %s', exc)

        return None


