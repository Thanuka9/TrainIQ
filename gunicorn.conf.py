"""Gunicorn config for production web workers."""
import multiprocessing
import os

bind = os.getenv('GUNICORN_BIND', '0.0.0.0:5000')
workers = int(os.getenv('WEB_CONCURRENCY', max(2, multiprocessing.cpu_count())))
threads = int(os.getenv('GUNICORN_THREADS', '2'))
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
keepalive = int(os.getenv('GUNICORN_KEEPALIVE', '5'))
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
preload_app = os.getenv('GUNICORN_PRELOAD', 'true').lower() in ('1', 'true', 'yes')
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '2000'))
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '200'))

# Ensure production defaults when launched via gunicorn
os.environ.setdefault('RUN_SCHEDULER', 'false')
os.environ.setdefault('EVENT_BUS_CONSUMER', 'false')
