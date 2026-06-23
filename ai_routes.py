"""Shared AI job polling and utilities."""
from flask import Blueprint, jsonify
from flask_login import login_required, current_user

from utils.ai_jobs import get_job
from utils.tenant_utils import user_tenant_id

ai_routes = Blueprint("ai_routes", __name__)


@ai_routes.route("/jobs/<job_id>", methods=["GET"])
@login_required
def poll_ai_job(job_id):
    job = get_job(job_id, user_id=current_user.id, tenant_id=user_tenant_id())
    if not job:
        return jsonify({"error": "Job not found"}), 404

    payload = dict(job)
    if payload.get("status") == "running" and payload.get("total") and payload.get("done") is not None:
        try:
            payload["progress_pct"] = int(100 * float(payload["done"]) / float(payload["total"]))
        except (TypeError, ValueError, ZeroDivisionError):
            payload["progress_pct"] = None
    return jsonify(payload)
