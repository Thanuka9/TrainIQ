"""Third-party integrations health — Redis, email, Stripe (CEO module)."""

from __future__ import annotations



import logging

import os

import time

from typing import Any



logger = logging.getLogger(__name__)





def check_redis() -> dict[str, Any]:

    uri = (os.getenv('REDIS_URI') or '').strip()

    if not uri or uri.startswith('memory://'):

        return {

            'name': 'redis',

            'ok': True,

            'mode': 'memory',

            'latency_ms': 0,

            'detail': 'In-memory sessions/rate limits (single-worker). Set REDIS_URI for production cluster.',

        }

    start = time.perf_counter()

    try:

        import redis



        client = redis.from_url(uri, socket_connect_timeout=5)

        client.ping()

        latency_ms = round((time.perf_counter() - start) * 1000, 1)

        info: dict[str, Any] = {}

        try:

            mem = client.info('memory')

            clients = client.info('clients')

            info = {

                'used_memory_mb': round((mem.get('used_memory') or 0) / (1024 * 1024), 2),

                'peak_memory_mb': round((mem.get('used_memory_peak') or 0) / (1024 * 1024), 2),

                'connected_clients': clients.get('connected_clients'),

                'blocked_clients': clients.get('blocked_clients'),

            }

        except Exception:

            pass

        return {

            'name': 'redis',

            'ok': True,

            'mode': 'redis',

            'latency_ms': latency_ms,

            'detail': f'Connected ({latency_ms} ms)',

            **info,

        }

    except Exception as exc:

        return {

            'name': 'redis',

            'ok': False,

            'mode': 'redis',

            'latency_ms': round((time.perf_counter() - start) * 1000, 1),

            'detail': str(exc),

        }





def check_mail() -> dict[str, Any]:

    server = os.getenv('MAIL_SERVER', '')

    port = os.getenv('MAIL_PORT', '587')

    username = os.getenv('MAIL_USERNAME', '')

    use_tls = os.getenv('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')

    configured = bool(server and username)



    result: dict[str, Any] = {

        'name': 'email',

        'ok': configured,

        'configured': configured,

        'server': server or None,

        'port': port,

        'use_tls': use_tls,

        'detail': (

            f'SMTP {server}:{port}' if configured else

            'MAIL_SERVER / MAIL_USERNAME not set — transactional email disabled.'

        ),

    }



    if not configured:

        return result



    start = time.perf_counter()

    try:

        import smtplib



        with smtplib.SMTP(server, int(port), timeout=8) as smtp:

            smtp.ehlo()

            if use_tls:

                smtp.starttls()

                smtp.ehlo()

        result['latency_ms'] = round((time.perf_counter() - start) * 1000, 1)

        result['detail'] = f'SMTP reachable at {server}:{port} ({result["latency_ms"]} ms)'

    except Exception as exc:

        result['ok'] = False

        result['latency_ms'] = round((time.perf_counter() - start) * 1000, 1)

        result['detail'] = f'SMTP config present but connect failed: {exc}'



    return result





def check_stripe() -> dict[str, Any]:

    secret = (os.getenv('STRIPE_SECRET_KEY') or '').strip()

    webhook = (os.getenv('STRIPE_WEBHOOK_SECRET') or '').strip()

    publishable = (os.getenv('STRIPE_PUBLISHABLE_KEY') or '').strip()

    configured = bool(secret)



    result: dict[str, Any] = {

        'name': 'stripe',

        'ok': configured,

        'configured': configured,

        'webhook_configured': bool(webhook),

        'publishable_configured': bool(publishable),

        'detail': (

            'Stripe billing active' if configured else

            'Manual plan upgrades only — set STRIPE_SECRET_KEY for checkout.'

        ),

    }



    if not configured:

        return result



    start = time.perf_counter()

    try:

        import stripe



        stripe.api_key = secret

        stripe.Balance.retrieve()

        result['latency_ms'] = round((time.perf_counter() - start) * 1000, 1)

        result['detail'] = f'Stripe API OK ({result["latency_ms"]} ms)'

        result['ok'] = True

    except Exception as exc:

        result['latency_ms'] = round((time.perf_counter() - start) * 1000, 1)

        result['ok'] = False

        result['detail'] = f'Stripe key set but API failed: {exc}'



    return result





def get_integrations_status() -> dict[str, Any]:

    checks = [check_redis(), check_mail(), check_stripe()]

    failed = [c for c in checks if not c['ok'] and c['name'] == 'redis']

    degraded = any(not c['ok'] for c in checks)

    return {

        'status': 'degraded' if failed or degraded else 'healthy',

        'checks': checks,

        'latency_ms': {

            c['name']: c.get('latency_ms') for c in checks if c.get('latency_ms') is not None

        },

    }


