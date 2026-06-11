"""Shared AI job polling and utilities."""
from flask import Blueprint, jsonify, session

from utils.ai_jobs import get_job
from utils.tenant_utils import user_tenant_id

ai_routes = Blueprint("ai_routes", __name__)


@ai_routes.route("/jobs/<job_id>", methods=["GET"])
def poll_ai_job(job_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    job = get_job(job_id, user_id=user_id, tenant_id=user_tenant_id())
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job)
