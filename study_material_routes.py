from flask import Blueprint, request, jsonify, render_template, url_for, make_response, session, redirect, flash, Response, stream_with_context
from flask_login import login_required, current_user
import json as json_lib
from werkzeug.utils import secure_filename
import logging
from bson.objectid import ObjectId
from models import db, StudyMaterial, SubTopic, UserProgress, User, Level, Area, UserLevelProgress, Designation, Category, LevelArea
from datetime import datetime
from io import BytesIO
import PyPDF2
from docx import Document
from pptx import Presentation
from PIL import Image, ImageDraw
from io import BytesIO
from utils.progress_utils import has_finished_study
from utils.tenant_utils import (
    assert_tenant_access, user_tenant_id, filter_by_user_tenant,
    tenant_levels_query, tenant_categories_query, tenant_designations_query,
)
from utils.mongo_tenant import get_tenant_gridfs, open_grid_file
from utils.api_errors import handle_api_exception
import os
from dotenv import load_dotenv
from flask import current_app
from exams_routes import check_level_completion


# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Blueprint
study_material_routes = Blueprint('study_material_routes', __name__)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pptx', 'pdf', 'docx', 'txt'}
MAX_FILE_SIZE_MB = 100


def allowed_file(filename):
    """Check if a file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file_size(file, max_size_mb):
    """Validate if a file's size is within the specified limit."""
    file.seek(0, 2)  # move to end
    size = file.tell()
    file.seek(0)     # reset pointer
    return size <= max_size_mb * 1024 * 1024

def calculate_total_pages(file_like, filetype):
    """
    Calculate total pages/slides for a given file-like object based on its type.
    file_like should be a BytesIO or similar that we can seek(0).
    """
    try:
        file_like.seek(0)
        if filetype == 'pdf':
            reader = PyPDF2.PdfReader(file_like)
            return len(reader.pages)
        elif filetype == 'docx':
            doc = Document(file_like)
            word_count = sum(len(p.text.split()) for p in doc.paragraphs)
            # approximate pages by word count / 300
            return max(1, word_count // 300)
        elif filetype == 'pptx':
            presentation = Presentation(file_like)
            return len(presentation.slides)
        else:
            return 0  # unsupported
    except Exception as e:
        logging.error(f"Error calculating total pages for {filetype}: {e}")
        return 0

@study_material_routes.route('/upload_course', methods=['GET', 'POST'])
def upload_course():
    """
    Handle uploading of study materials and subtopics,
    with metadata in PostgreSQL and files in MongoDB (GridFS).
    """
    try:
        # Permission check
        if not session.get('is_super_admin', False):
            user_role = session.get('role')
            user_designation = session.get('designation_id')
            if user_role != 'admin' and user_designation not in [12]:
                flash("You do not have permission to upload study materials.", "error")
                return redirect(url_for('study_material_routes.list_study_materials'))

        # Render form
        if request.method == 'GET':
            return render_template('upload_study.html')

        # -------------------------
        # 1) Get Form Fields
        # -------------------------
        title       = request.form.get('title')
        description = request.form.get('description')
        course_time = request.form.get('course_time')
        max_time    = request.form.get('max_time')
        level_id    = request.form.get('level_id')
        category_id = request.form.get('category_id')
        # Always default to 1 if missing/invalid
        try:
            minimum_level = int(request.form.get('minimum_level') or 1)
        except ValueError:
            minimum_level = 1

        subtopic_titles = request.form.getlist('subtopic_titles')
        subtopic_files  = request.files.getlist('subtopic_files')

        # Basic validation
        if not (title and description and course_time and max_time):
            flash("All fields are required.", "error")
            return redirect(url_for('study_material_routes.upload_course'))

        try:
            course_time = int(course_time)
            max_time    = int(max_time)
        except ValueError:
            flash("Course time and max time must be integers.", "error")
            return redirect(url_for('study_material_routes.upload_course'))

        # Convert optional fk's
        try:
            level_id = int(level_id) if level_id else None
        except ValueError:
            level_id = None

        try:
            category_id = int(category_id) if category_id else None
        except ValueError:
            category_id = None

        # -------------------------
        # 2) Create StudyMaterial
        # -------------------------
        study_material = StudyMaterial(
            title=title,
            description=description,
            course_time=course_time,
            max_time=max_time,
            total_pages=0,
            files=[],
            level_id=level_id,
            category_id=category_id,
            minimum_level=minimum_level,
            tenant_id=user_tenant_id(),
        )
        db.session.add(study_material)
        db.session.commit()
        logging.info(f"Created study material with ID: {study_material.id}")

        # -------------------------
        # 3) Main Documents
        # -------------------------
        files = request.files.getlist('main_documents')
        file_ids = []
        total_pages = 0

        for file in files:
            if not (file and allowed_file(file.filename)):
                continue

            if not validate_file_size(file, MAX_FILE_SIZE_MB):
                flash(f"{file.filename} exceeds the {MAX_FILE_SIZE_MB}MB limit.", "error")
                continue

            data = file.read()
            tid = study_material.tenant_id or user_tenant_id()
            gfs = get_tenant_gridfs(tid)
            mongo_id = gfs.put(
                data,
                filename=secure_filename(file.filename),
                metadata={"tenant_id": tid, "study_material_id": study_material.id},
            )
            file_ids.append(f"{mongo_id}|{file.filename}")

            pages = calculate_total_pages(BytesIO(data), file.filename.rsplit('.',1)[1].lower())
            total_pages += pages

        study_material.files = file_ids
        study_material.total_pages = total_pages
        db.session.commit()
        logging.info(f"Main documents uploaded for study material ID: {study_material.id}")

        # -------------------------
        # 4) Subtopics
        # -------------------------
        for idx, title in enumerate(subtopic_titles):
            if not title:
                continue

            file = subtopic_files[idx] if idx < len(subtopic_files) else None
            sub_pages = 0
            sub_file_id = None

            if file and allowed_file(file.filename):
                if not validate_file_size(file, MAX_FILE_SIZE_MB):
                    flash(f"{file.filename} exceeds size limit.", "error")
                    continue

                data = file.read()
                tid = study_material.tenant_id or user_tenant_id()
                gfs = get_tenant_gridfs(tid)
                mongo_id = gfs.put(
                    data,
                    filename=secure_filename(file.filename),
                    metadata={"tenant_id": tid, "study_material_id": study_material.id},
                )
                sub_file_id = str(mongo_id)

                sub_pages = calculate_total_pages(BytesIO(data), file.filename.rsplit('.',1)[1].lower())

            sub = SubTopic(
                title=title,
                study_material_id=study_material.id,
                file_id=sub_file_id,
                page_count=sub_pages
            )
            db.session.add(sub)
            study_material.total_pages += sub_pages

        db.session.commit()
        logging.info(f"Subtopics uploaded for study material ID: {study_material.id}")

        flash("Study materials and subtopics uploaded successfully.", "success")
        return redirect(url_for('study_material_routes.list_study_materials'))

    except Exception as e:
        logging.error(f"Error in upload_course: {e}", exc_info=True)
        db.session.rollback()
        flash("An error occurred while uploading the course.", "error")
        return redirect(url_for('study_material_routes.upload_course'))

    
@study_material_routes.route('/start_course/<int:course_id>', methods=['POST'])
def start_course(course_id):
    """
    Start a course for a user and record the start date.
    """
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'User ID is required to start the course'}), 400

        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        study_material = StudyMaterial.query.get_or_404(course_id)
        assert_tenant_access(study_material)

        # Check access eligibility via our unified helper
        if not can_access_study_material(user, study_material):
            return jsonify({
                'error': 'You must complete earlier levels to access this course.'
            }), 403

        # Check if already started
        user_progress = UserProgress.query.filter_by(
            user_id=user_id,
            study_material_id=course_id
        ).first()

        if user_progress:
            logging.info(f"User {user_id} has already started course {course_id}.")
            return jsonify({
                'message': 'Course already started',
                'redirect_url': url_for('study_material_routes.view_course', course_id=course_id)
            }), 200

        # Start new course progress
        user_progress = UserProgress(
            user_id=user_id,
            study_material_id=course_id,
            pages_visited=0,
            progress_percentage=0,
            completion_date=None,
            start_date=datetime.utcnow()
        )
        db.session.add(user_progress)
        db.session.commit()

        logging.info(f"User {user_id} started course {course_id} at {user_progress.start_date}.")
        return jsonify({
            'success': 'Course started successfully',
            'start_date': user_progress.start_date.isoformat(),
            'redirect_url': url_for('study_material_routes.view_course', course_id=course_id)
        }), 201

    except Exception as e:
        logging.error(f"Error starting course: {e}", exc_info=True)
        return jsonify({'error': 'Failed to start course'}), 500


def can_access_level(user, level_id):
    """
    Check if the user can access the specified level.

    Access is granted if:
      1. user.current_level >= level_id (progress-based)
      2. user.designation.starting_level >= level_id (designation-based)
      3. OR — if level_id <= 1, everyone may see level 1 by default.
    Otherwise, require that all LevelArea rules for the previous level are met:
      • 100% study completion for each area
      • Exam passed if one is required (but skips allowed by designation)
    """
    try:
        # normalize user’s current level
        user_level = (
            user.get_current_level()
            if hasattr(user, "get_current_level")
            else getattr(user, "current_level", 0)
        ) or 0

        required = level_id or 0

        # 1) Progress-based
        if user_level >= required:
            return True

        # 2) Designation-based
        if (
            user.designation
            and getattr(user.designation, "starting_level", 0) >= required
        ):
            return True

        # 3) Level 1 is open to all
        if required <= 1:
            return True

        # 4) Gated by LevelArea entries for (required - 1)
        prev = required - 1
        level_areas = LevelArea.query.filter_by(level_id=prev).all()
        for la in level_areas:
            # a) study must be 100% complete
            if not has_finished_study(user.id, prev, la.area_id):
                return False

            # b) if an exam is specified, it must be passed (unless skipped)
            if la.required_exam_id:
                # skip only if designation allows
                if user.can_skip_exam(la.required_exam):
                    continue

                prog = (
                    UserLevelProgress.query
                    .filter_by(
                        user_id=user.id,
                        level_id=prev,
                        area_id=la.area_id,
                        passed=True
                    )
                    .first()
                )
                if not prog:
                    return False

        return True

    except Exception as e:
        logging.warning(f"Access level check failed: {e}")
        return False

# ----  Course Details  ----
@study_material_routes.route("/view_course/<int:course_id>")
def view_course(course_id):
    """
    Dashboard-style page that shows title, description,
    dates, overall progress, and a “Continue” link.
    No heavy file streaming happens here.
    """
    # 1 Fetch objects --------------------------------------------------
    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    subtopics      = SubTopic.query.filter_by(study_material_id=course_id).all()

    user_id = session.get("user_id")
    if not user_id:
        flash("Please log in.", "warning")
        return redirect(url_for("auth_routes.login"))

    user = User.query.get_or_404(user_id)
    if not can_access_study_material(user, study_material):
        flash("Complete previous levels to unlock this material.", "danger")
        return redirect(url_for("study_material_routes.list_study_materials"))
    # 2 Check user progress ---------------------------------------------
    user_progress = (UserProgress.query
                     .filter_by(user_id=user_id, study_material_id=course_id)
                     .first())

    if not user_progress:
        user_progress = UserProgress(
            user_id=user_id,
            study_material_id=course_id,
            pages_visited=0,
            progress_percentage=0,
            start_date=datetime.utcnow()
        )
        db.session.add(user_progress)
        db.session.commit()

    # 2 Pick the first PDF-id so the template can build the CTA
    first_doc_id = None
    if study_material.files:
        head_entry = study_material.files[0]
        if "|" in head_entry:
            first_doc_id, _ = head_entry.split("|", 1)

    continue_url = url_for("study_material_routes.course_content",
                           course_id=course_id,
                           file_id=first_doc_id) if first_doc_id else None

    # 3 Render
    return render_template(
        "view_course.html",
        study_material=study_material,
        subtopics=subtopics,
        user_progress=user_progress,
        continue_url=continue_url
    )

# ----  Document Viewer  --------------------------------------------
@study_material_routes.route("/course_content/<int:course_id>")
def course_content(course_id):
    """
    Streams PDFs / other docs in a dedicated viewer.
    ?file_id=<mongo-id> tells the page which file to open first.
    """

    user_id = session.get("user_id")
    if not user_id:
        flash("Please log in.", "warning")
        return redirect(url_for("auth_routes.login"))

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)

    # ---- Collect docs ------------------------------------------------
    requested_id = request.args.get("file_id")          # <<< NEW
    documents = []

    for entry in (study_material.files or []):
        if "|" not in entry:
            continue
        fid, filename = (p.strip() for p in entry.split("|", 1))
        try:
            gfile, _ = open_grid_file(fid, study_material.tenant_id)
        except Exception as e:
            current_app.logger.warning(f"GridFS fetch failed: {e}")
            continue

        ext = filename.lower().rsplit(".", 1)[-1]
        doc_type = ext if ext in ("pdf", "pptx", "docx", "txt") else "unsupported"

        documents.append({
            "id": str(gfile._id),
            "filename": filename,
            "type": doc_type,
            "content": gfile.read().decode() if doc_type == "txt" else None
        })

    # ---- Put the requested file first -------------------------------  <<< NEW
    if requested_id:
        documents.sort(key=lambda d: 0 if d["id"] == requested_id else 1)

    # ---- Progress record (unchanged) --------------------------------
    user_progress = (UserProgress.query
                     .filter_by(user_id=user_id, study_material_id=course_id)
                     .first())

    return render_template(
        "course_content.html",
        study_material=study_material,
        documents=documents,
        user_progress=user_progress
    )

@study_material_routes.route('/list', methods=['GET'])
def list_study_materials():
    """
    Render the list of all study materials with progress.
    """
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth_routes.login'))

    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('auth_routes.login'))

    # Get all study materials
    materials = filter_by_user_tenant(StudyMaterial.query, StudyMaterial).all()
    accessible_materials = []

    # Filter accessible study materials
    for material in materials:
        if can_access_study_material(user, material):
            accessible_materials.append(material)

    # Prepare progress data
    progress_data = []
    for material in accessible_materials:
        user_progress = UserProgress.query.filter_by(
            user_id=user.id,
            study_material_id=material.id
        ).first()
        progress_percentage = user_progress.progress_percentage if user_progress else 0
        progress_data.append({'course_id': material.id, 'progress_percentage': progress_percentage})

    # --- SORT by Course ID ---
    # Zip, sort, and unzip to keep both lists in sync
    combined = sorted(zip(accessible_materials, progress_data), key=lambda x: x[0].id)
    if combined:
        accessible_materials, progress_data = zip(*combined)
        accessible_materials, progress_data = list(accessible_materials), list(progress_data)
    else:
        accessible_materials, progress_data = [], []

    return render_template('list_study_materials.html', materials=accessible_materials, progress_data=progress_data)


@study_material_routes.route('/upload_page', methods=['GET'])
def upload_page():
    """
    Render the upload page only for authorized users.
    """
    if session.get('is_super_admin') or session.get('role') == 'admin':
        return render_template('upload_study.html')
    
    # Log unauthorized access attempt
    logging.warning(f"Unauthorized access attempt to upload page by user ID: {session.get('user_id')}")
    
    # Redirect unauthorized users
    flash("You do not have permission to upload study materials.", "danger")
    return redirect(url_for('study_material_routes.dashboard'))


@study_material_routes.route('/study_materials', methods=['GET'])
def study_materials():
    """
    Render the Study Materials dashboard.
    """
    return render_template('study_materials.html')


@study_material_routes.route("/update_progress", methods=["POST"])
def update_progress():
    """
    Called by the viewer whenever a page becomes 50 % visible.
    Updates pages_visited, progress %, completion_date, and (optionally) bumps the user level.
    """
    try:
        data              = request.json or {}
        user_id           = session.get("user_id")
        study_material_id = data.get("study_material_id")
        current_page      = int(data.get("current_page", 0))
        total_pages       = int(data.get("total_pages", 0))

        if not (user_id and study_material_id and total_pages):
            return jsonify(error="invalid input"), 400

        study_material = StudyMaterial.query.get_or_404(study_material_id)
        assert_tenant_access(study_material)
        if total_pages != study_material.total_pages:
            total_pages = study_material.total_pages  # always trust DB

        prog = (UserProgress.query
                .filter_by(user_id=user_id, study_material_id=study_material_id)
                .with_for_update()
                .first())

        if not prog:
            prog = UserProgress(
                user_id=user_id,
                study_material_id=study_material_id,
                pages_visited=current_page,
                start_date=datetime.utcnow()
            )
            db.session.add(prog)

        # advance page counter, but never exceed total_pages
        if current_page > prog.pages_visited:
            prog.pages_visited = min(current_page, total_pages)

        # compute % and cap at 100
        raw_pct = int(prog.pages_visited / total_pages * 100)
        prog.progress_percentage = min(raw_pct, 100)

        # stamp completion once (allow >= 100 to trigger)
        if prog.progress_percentage >= 100 and prog.completion_date is None:
            prog.progress_percentage = 100
            prog.completion_date = datetime.utcnow()
            prog.completed = True

        db.session.commit()

        # ---------- level-unlock check --------------------------------
        current_level = study_material.level_id or 0
        if current_level and prog.completed:
            # only advance when *all* areas + exams for this level are satisfied
            if check_level_completion(user_id, current_level):
                user = User.query.get(user_id)
                user.current_level = current_level + 1
                db.session.commit()
                flash(f"🎉 Level {current_level + 1} unlocked!", "success")

        return jsonify(
            success=True,
            progress_percentage=prog.progress_percentage,
            completed=prog.completed
        ), 200

    except Exception as e:
        logging.exception("update_progress failed")
        return handle_api_exception(e, user_message="Could not update progress.")

@study_material_routes.route('/stream_file/<file_id>', methods=['GET'])
@login_required
def stream_file(file_id):
    """Stream file content for inline display (tenant-scoped)."""
    from utils.file_access import require_material_file_access

    try:
        _material, grid_file = require_material_file_access(file_id)
        filename = grid_file.filename
        extension = f".{filename.rsplit('.', 1)[-1].lower()}"
        content_type_map = {
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain'
        }
        content_type = content_type_map.get(extension, None)

        if not content_type:
            logging.warning(f"Unsupported file type for file ID {file_id}: {filename}")
            return jsonify({'error': f'Unsupported file type: {extension}'}), 400

        # Stream the file content in chunks
        def generate():
            try:
                while chunk := grid_file.read(8192):  # Read in 8KB chunks
                    yield chunk
            except Exception as e:
                logging.error(f"Error reading file ID {file_id} in chunks: {e}")
                raise

        # Prepare the response with appropriate headers
        response = make_response(generate())
        response.headers['Content-Type'] = content_type
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        response.headers['Cache-Control'] = 'no-store'  # Prevent caching
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'; script-src 'self';"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'

        logging.info(f"Successfully streamed file with ID {file_id} ({filename})")
        return response

    except FileNotFoundError:
        logging.error(f"File with ID {file_id} does not exist in GridFS.")
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logging.error(f"Error streaming file with ID {file_id}: {e}")
        return jsonify({'error': 'Failed to stream file.'}), 500


@study_material_routes.route('/update_time', methods=['POST'])
def update_time():
    """
    Add elapsed seconds to UserProgress.total_time.
    The viewer sends chunks (default 30 s) while the tab is visible.
    """
    try:
        data         = request.json or {}
        delta        = int(data.get('elapsed_time', 0))
        material_id  = data.get('study_material_id')
        user_id      = session.get('user_id')

        if not user_id or not material_id:
            return jsonify(error="missing ids"), 400
        if delta <= 0:
            return jsonify(success=True)          # ignore zero/neg chunks

        prog = (UserProgress.query
                .filter_by(user_id=user_id, study_material_id=material_id)
                .with_for_update()
                .first())

        if not prog:
            return jsonify(error="progress not found"), 404

        # sanity-check: don’t let a single chunk exceed total possible time.
        if prog.start_date:
            max_allowed = (datetime.utcnow() - prog.start_date).total_seconds() + 300
            if delta > max_allowed:
                return jsonify(error="elapsed_time too large"), 400

        prog.time_spent = (prog.time_spent or 0) + delta
        db.session.commit()
        return jsonify(success=True)

    except Exception as e:
        logging.exception("update_time failed")
        return handle_api_exception(e, user_message="Could not update progress.")


@study_material_routes.route('/download_file/<file_id>', methods=['GET'])
@login_required
def download_file(file_id):
    """Download a study file (tenant-scoped)."""
    from utils.file_access import require_material_file_access

    try:
        _material, grid_file = require_material_file_access(file_id)
        if not grid_file:
            logging.error(f"File with ID {file_id} not found in GridFS.")
            return jsonify({'error': 'File not found'}), 404

        # Create response with the file data
        filename = grid_file.filename
        response = make_response(grid_file.read())
        response.headers['Content-Type'] = 'application/octet-stream'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        logging.info(f"File downloaded successfully with ID {file_id} ({filename})")
        return response
    except Exception as e:
        logging.error(f"Error downloading file with ID {file_id}: {e}")
        return jsonify({'error': 'Failed to download file.'}), 500

@study_material_routes.route('/dashboard', methods=['GET'])
def dashboard():
    """
    Render the study materials dashboard with super admin access check.
    """
    # Ensure user is logged in
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth_routes.login'))

    # Fetch is_super_admin directly from the database
    user = User.query.get(user_id)
    is_super_admin = user.is_super_admin if user else False

    # Pass the result to the template
    return render_template('dashboard.html', is_super_admin=is_super_admin)


def can_access_study_material(user, study_material):
    """
    Return True if the user may access this study_material, based on:
      1) minimum_level == 0 → unrestricted
      2) user.designation.starting_level >= minimum_level
      3) user.get_current_level() >= minimum_level
    """
    # 1) Get the gate level (default 0 if somehow None)
    min_level = study_material.minimum_level or 0

    # 2) Everyone gets free access to level-0 (or level-1) materials
    if min_level <= 1:
        return True

    # 3) Try to coerce user level to int
    try:
        user_level = int(user.get_current_level() or 0)
    except (TypeError, ValueError):
        user_level = 0

    # 4) Check designation override
    if user.designation and getattr(user.designation, "starting_level", 0) >= min_level:
        return True

    # 5) Check actual user progress
    if user_level >= min_level:
        return True

    return False


def extract_text_from_gridfs(file_id, page_num=None, tenant_id=None):
    """Extract plain text from a GridFS document for LearnIQ context."""
    try:
        gfile, _ = open_grid_file(file_id, tenant_id)
        raw = gfile.read()
        filename = gfile.filename or ""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"
        buf = BytesIO(raw)

        if ext == "pdf":
            reader = PyPDF2.PdfReader(buf)
            if page_num and 1 <= page_num <= len(reader.pages):
                idx = page_num - 1
                window = []
                for i in range(max(0, idx - 1), min(len(reader.pages), idx + 2)):
                    t = reader.pages[i].extract_text() or ""
                    if t.strip():
                        label = "CURRENT PAGE" if i == idx else f"Page {i + 1}"
                        window.append(f"[{label}]\n{t}")
                return "\n\n".join(window)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if ext == "docx":
            doc = Document(buf)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if ext == "pptx":
            prs = Presentation(buf)
            slides = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slides.append(shape.text)
            return "\n".join(slides)
        if ext == "txt":
            return raw.decode("utf-8", errors="ignore")
        return ""
    except Exception as e:
        logging.error(f"Text extraction failed for {file_id}: {e}")
        return ""


def _get_course_document_text(study_material, file_id=None, page_num=None):
    """Build combined text context from course files."""
    tid = study_material.tenant_id
    parts = []
    if file_id:
        text = extract_text_from_gridfs(file_id, page_num=page_num, tenant_id=tid)
        if text.strip():
            return text
    for entry in (study_material.files or []):
        if "|" not in entry:
            continue
        fid, _ = (p.strip() for p in entry.split("|", 1))
        text = extract_text_from_gridfs(fid, tenant_id=tid)
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


@study_material_routes.route('/ai/status', methods=['GET'])
def learniq_status():
    """Check if local Ollama/Gemma 4 is available."""
    from utils.local_ai import get_ai_status
    return jsonify(get_ai_status())


def _ai_unavailable_response():
    from utils.local_ai import get_ai_status
    status = get_ai_status()
    return jsonify({"error": status["message"], **status}), 503


def _learniq_context(study_material, data):
    """Parse LearnIQ request fields; allow vision fallback when text is sparse."""
    from utils.local_ai import resolve_model, needs_vision_fallback
    from utils import ai_cache

    file_id = data.get("file_id")
    page_num = data.get("current_page")
    doc_text = _get_course_document_text(study_material, file_id, page_num=page_num)

    page_image = None
    if data.get("use_vision") and data.get("page_image"):
        page_image = data.get("page_image")
    elif not doc_text.strip() and data.get("page_image"):
        page_image = data.get("page_image")
    page_images = [page_image] if page_image else None

    if not doc_text.strip() and not page_images:
        return None, jsonify({
            "error": "No extractable text found. Open a PDF page or ensure documents are uploaded."
        }), 400

    model = resolve_model()
    cache_key = ai_cache.make_key(
        data.get("_cache_feature", "learniq"),
        study_material.id,
        file_id,
        page_num,
        model,
    )
    return {
        "file_id": file_id,
        "page_num": page_num,
        "page_images": page_images,
        "doc_text": doc_text,
        "model": model,
        "cache_key": cache_key,
        "use_vision": needs_vision_fallback(doc_text, page_images),
    }, None, None


@study_material_routes.route('/ai/summarize/<int:course_id>', methods=['POST'])
def learniq_summarize_route(course_id):
    from utils.local_ai import learniq_summarize, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    data["_cache_feature"] = "summarize"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    from utils import ai_cache
    cached = ai_cache.get(ctx["cache_key"])
    if cached:
        return jsonify({"summary": cached["summary"], "feature": "LearnIQ", "cached": True})

    try:
        summary = learniq_summarize(
            study_material.title, ctx["doc_text"], page_images=ctx["page_images"]
        )
        ai_cache.set(ctx["cache_key"], {"summary": summary})
        return jsonify({
            "summary": summary,
            "feature": "LearnIQ",
            "cached": False,
            "vision": ctx["use_vision"],
        })
    except ConnectionError as e:
        return jsonify({"error": "AI service is temporarily unavailable."}), 503


@study_material_routes.route('/ai/stream/summarize/<int:course_id>', methods=['POST'])
def learniq_stream_summarize_route(course_id):
    from utils.local_ai import learniq_summarize_stream, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    data["_cache_feature"] = "summarize"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    from utils import ai_cache
    cached = ai_cache.get(ctx["cache_key"])

    def generate():
        if cached:
            yield f"data: {json_lib.dumps({'text': cached['summary'], 'cached': True})}\n\n"
            yield f"data: {json_lib.dumps({'done': True, 'cached': True})}\n\n"
            return
        parts = []
        try:
            for chunk in learniq_summarize_stream(
                study_material.title, ctx["doc_text"], page_images=ctx["page_images"]
            ):
                parts.append(chunk)
                yield f"data: {json_lib.dumps({'text': chunk})}\n\n"
            summary = "".join(parts)
            ai_cache.set(ctx["cache_key"], {"summary": summary})
            yield f"data: {json_lib.dumps({'done': True, 'cached': False, 'vision': ctx['use_vision']})}\n\n"
        except ConnectionError as e:
            yield f"data: {json_lib.dumps({'error': 'An error occurred.'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@study_material_routes.route('/ai/flashcards/<int:course_id>', methods=['POST'])
def learniq_flashcards_route(course_id):
    from utils.local_ai import learniq_flashcards, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    data["_cache_feature"] = "flashcards"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    from utils import ai_cache
    cached = ai_cache.get(ctx["cache_key"])
    if cached:
        return jsonify({"flashcards": cached["flashcards"], "feature": "LearnIQ", "cached": True})

    try:
        cards = learniq_flashcards(
            study_material.title, ctx["doc_text"], page_images=ctx["page_images"]
        )
        ai_cache.set(ctx["cache_key"], {"flashcards": cards})
        return jsonify({
            "flashcards": cards,
            "feature": "LearnIQ",
            "cached": False,
            "vision": ctx["use_vision"],
        })
    except ConnectionError as e:
        return jsonify({"error": "AI service is temporarily unavailable."}), 503


@study_material_routes.route('/ai/chat/<int:course_id>', methods=['POST'])
def learniq_chat_route(course_id):
    from utils.local_ai import learniq_chat, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required."}), 400

    data["_cache_feature"] = "chat"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    try:
        reply = learniq_chat(
            study_material.title,
            ctx["doc_text"],
            message,
            data.get("history", []),
            page_images=ctx["page_images"],
        )
        return jsonify({"reply": reply, "feature": "LearnIQ", "vision": ctx["use_vision"]})
    except ConnectionError as e:
        return jsonify({"error": "AI service is temporarily unavailable."}), 503


@study_material_routes.route('/ai/stream/chat/<int:course_id>', methods=['POST'])
def learniq_stream_chat_route(course_id):
    from utils.local_ai import learniq_chat_stream, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required."}), 400

    data["_cache_feature"] = "chat"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    def generate():
        try:
            for chunk in learniq_chat_stream(
                study_material.title,
                ctx["doc_text"],
                message,
                data.get("history", []),
                page_images=ctx["page_images"],
            ):
                yield f"data: {json_lib.dumps({'text': chunk})}\n\n"
            yield f"data: {json_lib.dumps({'done': True, 'vision': ctx['use_vision']})}\n\n"
        except ConnectionError as e:
            yield f"data: {json_lib.dumps({'error': 'An error occurred.'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@study_material_routes.route('/ai/stream/sample_questions/<int:course_id>', methods=['POST'])
def learniq_stream_sample_questions_route(course_id):
    from utils.local_ai import learniq_sample_questions_stream, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    data["_cache_feature"] = "sample_questions"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    from utils import ai_cache
    cached = ai_cache.get(ctx["cache_key"])

    def generate():
        if cached:
            yield f"data: {json_lib.dumps({'text': cached['questions'], 'cached': True})}\n\n"
            yield f"data: {json_lib.dumps({'done': True, 'cached': True})}\n\n"
            return
        parts = []
        try:
            for chunk in learniq_sample_questions_stream(
                study_material.title, ctx["doc_text"], page_images=ctx["page_images"]
            ):
                parts.append(chunk)
                yield f"data: {json_lib.dumps({'text': chunk})}\n\n"
            ai_cache.set(ctx["cache_key"], {"questions": "".join(parts)})
            yield f"data: {json_lib.dumps({'done': True, 'cached': False, 'vision': ctx['use_vision']})}\n\n"
        except ConnectionError:
            yield f"data: {json_lib.dumps({'error': 'AI service is temporarily unavailable.'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@study_material_routes.route('/ai/sample_questions/<int:course_id>', methods=['POST'])
@study_material_routes.route('/ai/quiz/<int:course_id>', methods=['POST'])
def learniq_quiz_json(course_id):
    """Non-streaming Quiz Me fallback (also used when SSE route is unavailable)."""
    from utils.local_ai import learniq_sample_questions, is_available
    from utils.ai_rate_limit import check_ai_rate_limit

    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    study_material = StudyMaterial.query.get_or_404(course_id)
    assert_tenant_access(study_material)
    user = User.query.get(session["user_id"])
    if not can_access_study_material(user, study_material):
        return jsonify({"error": "Access denied"}), 403
    if not is_available():
        return _ai_unavailable_response()

    data = request.get_json(silent=True) or {}
    data["_cache_feature"] = "sample_questions"
    ctx, err_resp, _ = _learniq_context(study_material, data)
    if err_resp:
        return err_resp

    from utils import ai_cache
    cached = ai_cache.get(ctx["cache_key"])
    if cached:
        return jsonify({
            "questions": cached["questions"],
            "feature": "LearnIQ",
            "cached": True,
            "vision": ctx["use_vision"],
        })

    try:
        questions = learniq_sample_questions(
            study_material.title, ctx["doc_text"], page_images=ctx["page_images"]
        )
        ai_cache.set(ctx["cache_key"], {"questions": questions})
        return jsonify({
            "questions": questions,
            "feature": "LearnIQ",
            "cached": False,
            "vision": ctx["use_vision"],
        })
    except ConnectionError:
        return jsonify({"error": "AI service is temporarily unavailable."}), 503


@study_material_routes.route('/get_dropdowns', methods=['GET'])
@login_required
def get_dropdowns():
    """Fetch tenant-scoped Levels, Categories, and Designations."""
    try:
        levels = tenant_levels_query().order_by(Level.level_number.asc()).all()
        categories = tenant_categories_query().order_by(Category.id.asc()).all()
        designations = tenant_designations_query().order_by(Designation.id.asc()).all()

        # Constructing JSON response
        data = {
            "levels": [{"id": level.id, "number": level.level_number} for level in levels],
            "categories": [{"id": category.id, "name": category.name} for category in categories],
            "designations": [{"id": designation.id, "title": designation.title} for designation in designations]
        }

        return jsonify(data), 200
    except Exception as e:
        logging.error(f"Error fetching dropdowns: {e}")
        return jsonify({"error": "Failed to fetch dropdowns"}), 500

