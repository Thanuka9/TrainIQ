"""Safe JSON API error responses — no internal details leaked to clients."""
import logging
from flask import jsonify


def json_error(message="An error occurred. Please try again later.", status=500):
    return jsonify({"error": message}), status


def handle_api_exception(exc, *, user_message=None, log_message=None):
    logging.error(log_message or "API error: %s", exc)
    return json_error(user_message or "An error occurred. Please try again later.", 500)
