"""LearnIQ / AI operations platform — Ollama, cache, jobs (CEO module)."""

from __future__ import annotations



import logging

import os

import time

from typing import Any



from utils.ops_constants import AI_BENCHMARK_ENABLED, AI_CACHE_MAX_MB, AI_LATENCY_WARN_MS



logger = logging.getLogger(__name__)





def probe_ollama_latency() -> dict[str, Any]:

    """Lightweight latency probe against local Ollama (no generation)."""

    import requests



    from utils.local_ai import OLLAMA_BASE, _bases



    bases = [OLLAMA_BASE.rstrip('/')] + [b for b in _bases() if b.rstrip('/') != OLLAMA_BASE.rstrip('/')]

    for base in bases:

        start = time.perf_counter()

        try:

            r = requests.get(f"{base}/api/tags", timeout=8)

            latency_ms = round((time.perf_counter() - start) * 1000, 1)

            if r.status_code == 200:

                return {

                    'ok': True,

                    'latency_ms': latency_ms,

                    'base': base,

                    'slow': latency_ms >= AI_LATENCY_WARN_MS,

                }

        except requests.exceptions.RequestException:

            continue

    return {'ok': False, 'latency_ms': None, 'base': None, 'slow': False}





def get_ai_cache_stats() -> dict[str, Any]:

    from utils import ai_cache



    return ai_cache.get_cache_stats()





def get_ai_ops_status() -> dict[str, Any]:

    """Full AI/LearnIQ ops snapshot."""

    from utils import ai_cache

    from utils.ai_jobs import _jobs, _lock

    from utils.local_ai import OLLAMA_BASE, OLLAMA_MODEL, get_ai_status



    status = get_ai_status()

    cache_stats = get_ai_cache_stats()



    with _lock:

        jobs = list(_jobs.values())

    running = sum(1 for j in jobs if j.get('status') == 'running')

    pending = sum(1 for j in jobs if j.get('status') == 'pending')

    failed = sum(1 for j in jobs if j.get('status') == 'failed')

    complete = sum(1 for j in jobs if j.get('status') == 'complete')



    latency = probe_ollama_latency() if AI_BENCHMARK_ENABLED else None



    overall = 'healthy'

    if not status.get('available'):

        overall = 'degraded'

    elif not status.get('model_ready'):

        overall = 'warning'

    elif cache_stats.get('over_capacity'):

        overall = 'warning'

    elif latency and latency.get('slow'):

        overall = 'warning'



    return {

        'status': overall,

        'engine': status.get('engine', 'ollama'),

        'available': status.get('available', False),

        'model_ready': status.get('model_ready', False),

        'configured_model': OLLAMA_MODEL,

        'resolved_model': status.get('resolved_model'),

        'installed_models': status.get('installed_models') or [],

        'ollama_base': OLLAMA_BASE,

        'message': status.get('message', ''),

        'cache': cache_stats,

        'capacity': {

            'max_cache_mb': AI_CACHE_MAX_MB,

            'over_capacity': cache_stats.get('over_capacity', False),

            'cache_ttl_hours': int(ai_cache.CACHE_TTL) // 3600,

        },

        'latency': latency,

        'jobs': {

            'total': len(jobs),

            'running': running,

            'pending': pending,

            'failed': failed,

            'complete': complete,

        },

        'rate_limits': {

            'per_hour': int(os.getenv('AI_RATE_LIMIT_HOUR', '20')),

            'per_minute': int(os.getenv('AI_RATE_LIMIT_MINUTE', '5')),

        },

    }





def clear_ai_cache(*, expired_only: bool = False) -> dict[str, Any]:

    """Remove LearnIQ disk cache files."""

    from utils import ai_cache



    ai_cache._ensure_dir()

    removed = 0

    errors = 0

    now = time.time()

    for fname in os.listdir(ai_cache.CACHE_DIR):

        if not fname.endswith('.json'):

            continue

        path = os.path.join(ai_cache.CACHE_DIR, fname)

        try:

            if expired_only and now - os.path.getmtime(path) <= ai_cache.CACHE_TTL:

                continue

            os.remove(path)

            removed += 1

        except OSError:

            errors += 1



    return {

        'ok': errors == 0,

        'removed': removed,

        'errors': errors,

        'mode': 'expired_only' if expired_only else 'all',

    }





def refresh_ai_engine() -> dict[str, Any]:

    """Refresh Ollama model discovery cache."""

    from utils.local_ai import _MODEL_CACHE, list_installed_models, resolve_model



    _MODEL_CACHE['resolved'] = None

    _MODEL_CACHE['installed'] = None

    list_installed_models(refresh=True)

    resolve_model()

    return get_ai_ops_status()





def bootstrap_ai() -> dict[str, Any]:

    """AI ops maintenance: refresh engine, purge expired cache, trim if over capacity."""

    steps = []

    try:

        clear_result = clear_ai_cache(expired_only=True)

        steps.append({

            'step': 'ai_cache_expired',

            'ok': clear_result.get('ok', False),

            'message': f"Removed {clear_result.get('removed', 0)} expired cache file(s).",

        })

    except Exception as exc:

        steps.append({'step': 'ai_cache_expired', 'ok': False, 'message': str(exc)})



    try:

        from utils import ai_cache



        trim = ai_cache.trim_to_capacity()

        if trim.get('removed', 0):

            steps.append({

                'step': 'ai_cache_trim',

                'ok': True,

                'message': (

                    f"Trimmed {trim['removed']} file(s), freed {trim['freed_mb']} MB "

                    f"(remaining {trim['remaining_mb']} MB)."

                ),

            })

    except Exception as exc:

        steps.append({'step': 'ai_cache_trim', 'ok': False, 'message': str(exc)})



    try:

        status = refresh_ai_engine()

        steps.append({

            'step': 'ai_engine_refresh',

            'ok': status.get('available', False),

            'message': status.get('message', 'Engine status refreshed.'),

        })

    except Exception as exc:

        steps.append({'step': 'ai_engine_refresh', 'ok': False, 'message': str(exc)})



    ok = all(s.get('ok') for s in steps)

    return {'status': 'success' if ok else 'partial', 'steps': steps, 'ai': get_ai_ops_status()}





def latest_ai_summary() -> dict[str, Any] | None:

    try:

        snap = get_ai_ops_status()

        return {

            'status': snap.get('status'),

            'model_ready': snap.get('model_ready'),

            'resolved_model': snap.get('resolved_model'),

            'cache_files': snap.get('cache', {}).get('files', 0),

            'cache_mb': snap.get('cache', {}).get('total_mb', 0),

            'latency_ms': (snap.get('latency') or {}).get('latency_ms'),

        }

    except Exception as exc:

        logger.debug('latest_ai_summary skipped: %s', exc)

        return None


