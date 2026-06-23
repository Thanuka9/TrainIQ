#!/usr/bin/env python
"""Production web entrypoint (gunicorn-compatible via app:app).

Sets RUN_SCHEDULER=false unless already configured.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('RUN_SCHEDULER', 'false')
os.environ.setdefault('EVENT_BUS_CONSUMER', 'false')


def main():
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', '5000')))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'

    from app import app

    print(f'TrainIQ web ({os.getenv("SERVICE_MODE", "full")}) on {host}:{port}')
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == '__main__':
    main()
