"""Redis Streams event bus for async ops actions (optional)."""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

STREAM_KEY = os.getenv('EVENT_BUS_STREAM', 'trainiq:ops:events')
CONSUMER_GROUP = os.getenv('EVENT_BUS_GROUP', 'trainiq-ops-workers')


def event_bus_enabled() -> bool:
    if os.getenv('EVENT_BUS_ENABLED', 'false').lower() not in ('1', 'true', 'yes'):
        return False
    return _redis_client() is not None


def _redis_client():
    uri = (os.getenv('REDIS_URI') or '').strip()
    if not uri or uri.startswith('memory://'):
        return None
    try:
        import redis

        client = redis.from_url(uri, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception as exc:
        logger.debug('[event_bus] Redis unavailable: %s', exc)
        return None


def _ensure_consumer_group(r) -> None:
    try:
        r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id='0', mkstream=True)
    except Exception as exc:
        if 'BUSYGROUP' not in str(exc):
            logger.debug('[event_bus] xgroup_create: %s', exc)


def publish_ops_event(event_type: str, payload: dict[str, Any]) -> str | None:
    """Publish ops event. Returns message id or None if bus disabled."""
    r = _redis_client()
    if r is None:
        return None
    body = {
        'type': event_type,
        'payload': json.dumps(payload, default=str),
        'id': uuid.uuid4().hex,
    }
    try:
        msg_id = r.xadd(STREAM_KEY, body, maxlen=10000, approximate=True)
        logger.info('[event_bus] published %s id=%s', event_type, msg_id)
        return msg_id
    except Exception as exc:
        logger.warning('[event_bus] publish failed: %s', exc)
        return None


def publish_agent_action(domain: str, action_id: str, *, actor_user_id: int | None) -> str | None:
    return publish_ops_event(
        'ops.agent_action',
        {'domain': domain, 'action_id': action_id, 'actor_user_id': actor_user_id},
    )


def publish_health_cycle(*, source: str, apply_safe: bool = False, actor_user_id: int | None = None) -> str | None:
    return publish_ops_event(
        'ops.health_cycle',
        {'source': source, 'apply_safe': apply_safe, 'actor_user_id': actor_user_id},
    )


def consume_ops_events(*, consumer_name: str, count: int = 5, block_ms: int = 2000) -> int:
    """Process pending ops events. Returns number handled."""
    r = _redis_client()
    if r is None:
        return 0

    _ensure_consumer_group(r)
    processed = 0
    try:
        batches = r.xreadgroup(
            CONSUMER_GROUP,
            consumer_name,
            {STREAM_KEY: '>'},
            count=count,
            block=block_ms,
        )
    except Exception as exc:
        logger.warning('[event_bus] xreadgroup failed: %s', exc)
        return 0

    if not batches:
        return 0

    for _stream, messages in batches:
        for msg_id, fields in messages:
            try:
                _dispatch_event(fields)
                r.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                processed += 1
            except Exception as exc:
                logger.error('[event_bus] handler failed msg=%s: %s', msg_id, exc)
    return processed


def _dispatch_event(fields: dict) -> None:
    event_type = fields.get('type') or ''
    raw = fields.get('payload') or '{}'
    payload = json.loads(raw) if isinstance(raw, str) else raw

    if event_type == 'ops.agent_action':
        from utils.ops_agents import execute_agent_action_sync

        execute_agent_action_sync(
            payload.get('domain', ''),
            payload.get('action_id', ''),
            actor_user_id=payload.get('actor_user_id'),
        )
    elif event_type == 'ops.health_cycle':
        from utils.platform_ops_orchestrator import run_health_cycle

        run_health_cycle(
            source=payload.get('source', 'event_bus'),
            apply_safe=bool(payload.get('apply_safe')),
            blocking_lock=True,
            actor_user_id=payload.get('actor_user_id'),
        )
    else:
        logger.debug('[event_bus] unknown event type: %s', event_type)
