from flask import Blueprint, request, jsonify, render_template
from extensions import db
from models import (Exam, Question, UserScore, User, Category, Level, Area, UserLevelProgress, 
    Designation, LevelArea, StudyMaterial, ExamAccessRequest, IncorrectAnswer, UserProgress)
from flask_login import current_user, login_required
from datetime import datetime, timezone, timedelta
from utils.exam_retry import (
    retry_period as exam_retry_period,
    special_exam_retry_period,
)
from utils.user_access import effective_is_super_admin
import random
import requests
from models import SpecialExamRecord
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from flask import session
from flask import redirect, flash, url_for
from utils.api_errors import handle_api_exception
from utils.progress_utils import has_finished_study
from utils.level_access import (
    check_level_completion,
    advance_user_level_after_completion,
    can_access_exam_level,
)
from utils.exam_grading import (
    get_passing_score, passed as exam_passed, calculate_grade as grade_by_threshold,
    grade_exam, score_question, DEFAULT_PASSING_SCORE,
)
from utils.tenant_utils import (
    assert_tenant_access, user_tenant_id,
    tenant_levels_query, tenant_categories_query, tenant_areas_query,
    tenant_designations_query, tenant_courses_query,
)

# Blueprint setup
exams_routes = Blueprint('exams_routes', __name__)

# -------------------------------
# Route to Create an Exam 
# -------------------------------
def _exam_create_form_context():
    """Shared dropdown data for exam creation templates."""
    levels = tenant_levels_query().order_by(Level.level_number.asc()).all()
    categories = tenant_categories_query().order_by(Category.id.asc()).all()
    designations = tenant_designations_query().order_by(Designation.id.asc()).all()
    areas = tenant_areas_query().all()
    courses_q = (
        tenant_courses_query()
        .options(joinedload(StudyMaterial.level), joinedload(StudyMaterial.category))
        .order_by(StudyMaterial.title)
        .all()
    )
    from utils.course_assets import course_picker_row
    courses = [course_picker_row(c) for c in courses_q]
    return {
        "levels": [{"id": lvl.id, "level_number": lvl.level_number} for lvl in levels],
        "categories": [{"id": cat.id, "name": cat.name} for cat in categories],
        "areas": [{"id": a.id, "name": a.name} for a in areas],
        "designation_levels": [{"id": des.id, "title": des.title} for des in designations],
        "courses": courses,
    }


@exams_routes.route('/create', methods=['GET', 'POST'])
@login_required
def create_exam():
    """
    Route to create an exam.
    Accessible only to super admins.
    Ensures exam is linked to a Level, Area, and Category.
    Also allows setting a Minimum Designation Level for exam eligibility.
    """
    # -------------------------------
    # Authorization Check
    # -------------------------------
    if not effective_is_super_admin(current_user):
        logging.warning("Unauthorized access attempt by user ID: %s", current_user.id)
        if request.method == 'GET':
            return render_template('403.html'), 403
        return jsonify({'error': 'Unauthorized access'}), 403

    if request.method == 'GET':
        try:
            return render_template('create_exam_hub.html')
        except Exception as e:
            logging.error(f"Error rendering exam creation hub: {e}")
            return render_template('500.html', error="Failed to load the exam creation page."), 500

    # -------------------------------
    # POST Request: Handle Exam Creation
    # -------------------------------
    if request.method == 'POST':
        try:
            form = request.form
            # 1) Extract and validate all exam‐level fields
            title       = form.get('title', '').strip()
            duration    = form.get('duration', '').strip()
            level_id    = form.get('level_id', '').strip()
            category_id = form.get('category_id', '').strip()
            course_id   = form.get('course_id', '').strip()
            min_desig   = (form.get('minimum_designation_id') or form.get('minimum_designation_level') or '').strip()

            if not all([title, duration, level_id, category_id, course_id, min_desig]):
                return jsonify({'error': 'All fields are required'}), 400
            if not duration.isdigit() or int(duration) <= 0:
                return jsonify({'error': 'Duration must be a positive integer'}), 400

            # 2) Load tenant-scoped FK objects
            level       = tenant_levels_query().filter_by(id=int(level_id)).first()
            category    = tenant_categories_query().filter_by(id=int(category_id)).first()
            course      = tenant_courses_query().filter_by(id=int(course_id)).first()
            designation = tenant_designations_query().filter_by(id=int(min_desig)).first()

            area = (
                tenant_areas_query().filter(Area.name.ilike(category.name)).first()
                if category else None
            )
            if not area and category:
                area = tenant_areas_query().first()

            for obj, name in [
                (level, 'Level'),
                (category, 'Category'),
                (area, 'Area'),
                (course, 'Course'),
                (designation, 'Designation')
            ]:
                if not obj:
                    return jsonify({'error': f'Selected {name} is not valid for your organization'}), 400
            assert_tenant_access(course)

            # 3) Create & commit the Exam
            passing_raw = form.get('passing_score', '').strip()
            passing_score = float(passing_raw) if passing_raw else 70.0
            retry_raw = (form.get('retry_cooldown_days') or '').strip()
            retry_cooldown = int(retry_raw) if retry_raw.isdigit() else None

            exam = Exam(
                title                     = title,
                duration                  = int(duration),
                level_id                  = level.id,
                area_id                   = area.id,
                category_id               = category.id,
                course_id                 = course.id,
                created_by                = current_user.id,
                minimum_level             = level.level_number,
                minimum_designation_id = designation.id,
                tenant_id                 = user_tenant_id(),
                passing_score             = passing_score,
                retry_cooldown_days       = retry_cooldown,
            )
            db.session.add(exam)
            db.session.commit()

            # 4) Return the URL where the front-end must POST the questions
            add_q_url = url_for('exams_routes.add_questions', exam_id=exam.id)

            return jsonify({
                'message': 'Exam created successfully',
                'exam_id': exam.id,
                'add_questions_url': add_q_url
            }), 201

        except SQLAlchemyError as db_error:
            logging.error(f"Database error creating exam: {db_error}")
            db.session.rollback()
            return jsonify({'error': 'Database error. Please try again later.'}), 500

        except Exception as e:
            logging.error(f"Unexpected error creating exam: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to create exam. Please try again later.'}), 500


@exams_routes.route('/create/custom', methods=['GET'])
@login_required
def create_exam_custom():
    if not effective_is_super_admin(current_user):
        return render_template('403.html'), 403
    try:
        return render_template('create_exam_custom.html', **_exam_create_form_context())
    except Exception as e:
        logging.error(f"Error rendering custom exam form: {e}")
        return render_template('500.html', error="Failed to load custom exam builder."), 500


@exams_routes.route('/create/ai', methods=['GET'])
@login_required
def create_exam_ai():
    if not effective_is_super_admin(current_user):
        return render_template('403.html'), 403
    try:
        return render_template('create_exam_ai.html', **_exam_create_form_context())
    except Exception as e:
        logging.error(f"Error rendering AI exam form: {e}")
        return render_template('500.html', error="Failed to load AI exam generator."), 500


@exams_routes.route('/upload_exam', methods=['GET'])
@login_required
def upload_exam_legacy_redirect():
    """Legacy URL — redirect to exam creation hub."""
    return redirect(url_for('exams_routes.create_exam'))


# -------------------------------
# Route to Add Questions to an Exam
# -------------------------------
@exams_routes.route('/<int:exam_id>/add_questions', methods=['POST'])
@login_required
def add_questions(exam_id):
    """
    Add questions to an existing exam, allowing correct answers as text,
    numeric index ("2" → second choice), or letter ("B" → second choice).
    """
    if not effective_is_super_admin(current_user):
        logging.warning(f"Unauthorized access by user {current_user.id} to add questions.")
        return jsonify({'error': 'Unauthorized access'}), 403

    try:
        # Validate exam existence
        exam = Exam.query.get_or_404(exam_id)
        assert_tenant_access(exam)

        # Parse the form data into a dictionary of question entries
        data = request.form.to_dict(flat=False)
        questions = {}
        errors = []
        questions_to_add = []

        # Group fields by question index
        for key, value in data.items():
            if key.startswith("questions["):
                parts = key.split('][')
                question_index = parts[0].split('[')[1]
                field = parts[1].rstrip(']')
                questions.setdefault(question_index, {})[field] = value[0].strip()

        # Process and validate each question
        for question_index, qdata in questions.items():
            try:
                question_text      = qdata.get('question_text','').strip()
                question_type      = qdata.get('question_type', 'single_choice').strip() or 'single_choice'
                choices_raw        = qdata.get('choices','').strip(' ,')
                raw_answer         = qdata.get('correct_answer','').strip(' "\'')
                reference_answer   = qdata.get('reference_answer','').strip()
                category_id        = qdata.get('category_id','').strip()

                if question_type == 'structured':
                    if not all([question_text, reference_answer, category_id]):
                        errors.append(f"Question {question_index}: Text, reference answer, and category required")
                        continue
                    if not tenant_categories_query().filter_by(id=int(category_id)).first():
                        errors.append(f"Question {question_index}: Invalid category ID")
                        continue
                    questions_to_add.append(Question(
                        exam_id=exam_id,
                        question_text=question_text,
                        choices='',
                        correct_answer=reference_answer,
                        category_id=int(category_id),
                        question_type='structured',
                    ))
                    continue

                # Required fields check (choice-based types)
                if not all([question_text, choices_raw, raw_answer, category_id]):
                    errors.append(f"Question {question_index}: All fields are required")
                    continue

                # Split and clean choice strings
                choices_list = [c.strip() for c in choices_raw.split(',') if c.strip()]
                if len(choices_list) < 2:
                    errors.append(f"Question {question_index}: At least 2 choices required")
                    continue

                # Duplicate check (case-insensitive)
                if len(choices_list) != len({c.lower() for c in choices_list}):
                    errors.append(f"Question {question_index}: Duplicate choices found (case-insensitive)")
                    continue

                # Normalize correct answer input
                corr = raw_answer.upper()
                # Numeric index: "2" → second choice
                if corr.isdigit():
                    idx = int(corr) - 1
                    if 0 <= idx < len(choices_list):
                        corr = choices_list[idx]
                    else:
                        errors.append(f"Question {question_index}: Answer index {raw_answer} out of range")
                        continue
                # Letter index: "B" → second choice
                elif len(corr) == 1 and 'A' <= corr <= 'Z':
                    idx = ord(corr) - ord('A')
                    if 0 <= idx < len(choices_list):
                        corr = choices_list[idx]

                # Final membership check (single / multiple choice letters or text)
                if question_type == 'multiple_choice':
                    letters = [p.strip().upper() for p in raw_answer.replace('|', ',').split(',') if p.strip()]
                    valid_letters = {chr(ord('A') + i) for i in range(len(choices_list))}
                    if not letters or not all(l in valid_letters for l in letters):
                        errors.append(f"Question {question_index}: Invalid multi-select answer keys")
                        continue
                    corr = ','.join(sorted(set(letters)))
                elif corr not in choices_list:
                    errors.append(
                        f"Question {question_index}: Correct answer must match one of the choices. "
                        f"Got '{raw_answer}', Choices: {choices_list}"
                    )
                    continue

                # Validate category exists (tenant-scoped)
                if not tenant_categories_query().filter_by(id=int(category_id)).first():
                    errors.append(f"Question {question_index}: Invalid category ID")
                    continue

                # Create Question model instance
                q = Question(
                    exam_id        = exam_id,
                    question_text  = question_text,
                    choices        = ','.join(choices_list),
                    correct_answer = corr,
                    category_id    = int(category_id),
                    question_type  = question_type,
                )
                questions_to_add.append(q)

            except Exception as qe:
                logging.error(f"Error processing question {question_index}: {qe}")
                errors.append(f"Question {question_index}: Invalid input format")

        # Bulk insert valid questions
        if questions_to_add:
            try:
                db.session.bulk_save_objects(questions_to_add)
                db.session.commit()
                logging.info(f"Added {len(questions_to_add)} questions to Exam {exam_id}")
            except Exception as db_err:
                db.session.rollback()
                logging.error(f"Database error saving questions: {db_err}")
                errors.append("Failed to save questions due to database error")

        # Return response
        if errors:
            return jsonify({
                'message':       f"Processed with {len(errors)} errors",
                'success_count': len(questions_to_add),
                'errors':        errors
            }), 207

        return jsonify({
            'message': f"Successfully added {len(questions_to_add)} questions",
            'exam_id': exam_id
        }), 201

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Internal server error'}), 500

    
# ---------------------------------------
# List Exams Route
# ---------------------------------------
@exams_routes.route('/list', methods=['GET'])
@login_required
def list_exams():
    """
    Build the exam dashboard for the current user.
    """
    try:
        user_id          = current_user.id
        now              = datetime.utcnow()
        tid              = user_tenant_id()
        special_retry_p1 = special_exam_retry_period(tid, 1)
        special_retry_p2 = special_exam_retry_period(tid, 2)
        current_level    = current_user.get_current_level()

        # ── Base queries ─────────────────────────────────────────────
        exam_q = (
            Exam.query
                .options(
                    db.joinedload(Exam.level),
                    db.joinedload(Exam.area),
                    db.joinedload(Exam.category)
                )
        )
        if tid:
            exam_q = exam_q.filter(Exam.tenant_id == tid)
        exams = exam_q.order_by(Exam.level_id.asc(), Exam.title.asc()).all()

        exam_scores = {
            s.exam_id: s
            for s in UserScore.query
                                .filter_by(user_id=user_id)
                                .order_by(UserScore.created_at.desc())
                                .all()
        }

        processed_exams = []

        # ── Main loop for regular exams ──────────────────────────────
        for exam in exams:
            score_record = exam_scores.get(exam.id)

            access_request = (
                ExamAccessRequest.query
                .filter_by(user_id=user_id, exam_id=exam.id)
                .order_by(ExamAccessRequest.requested_at.desc())
                .first()
            )

            # 1) STUDY-COMPLETION CHECK (must complete exact course)
            prog = UserProgress.query.filter_by(
                user_id=user_id,
                study_material_id=exam.course_id,
                completed=True
            ).first()
            study_complete = True if prog else False

            # 2) CAN-SKIP and LEVEL-GATING
            can_skip      = exam.is_skippable(current_user)
            level_allowed = can_access_exam_level(current_user, exam)
            if not level_allowed:
                continue  # hide exams above user’s level

            # 3) Build base exam_data payload
            exam_data = {
                'exam_id'     : exam.id,
                'title'       : exam.title,
                'duration'    : exam.duration,
                'category'    : exam.category.name if exam.category else 'General',
                'level'       : exam.level.level_number,
                'retry_date'  : None,
                'can_retry'   : False,
                'attempts'    : score_record.attempts if score_record else 0,
                'status'      : '',
                'can_request' : False,
                'route'       : 'exams_routes.start_exam'
            }

            # 4) Enforce STUDY REQUIREMENT
            if not study_complete:
                if can_skip and not score_record:
                    exam_data['status'] = 'Skipped (optional)'
                else:
                    exam_data['status'] = 'Study Material Not Completed'
                    processed_exams.append(exam_data)
                    continue

            # 5) ACCESS CONTROL on FIRST ATTEMPT
            if not score_record:
                if (
                    not access_request
                    or access_request.status != 'approved'
                    or access_request.used
                ):
                    exam_data['status'] = 'Access Required'
                    if (
                        not access_request
                        or access_request.status == 'rejected'
                        or access_request.used
                    ):
                        exam_data['can_request'] = True
                    processed_exams.append(exam_data)
                    continue

            # 6) SCORE & RETRY LOGIC
            if not score_record:
                exam_data.update({
                    'status'   : 'Start Exam',
                    'can_retry': True
                })
            else:
                next_try      = score_record.created_at + exam_retry_period(exam)
                can_retry_now = (now >= next_try)
                exam_data['retry_date'] = next_try.date().isoformat()

                if score_record.score >= get_passing_score(exam):
                    exam_data.update({
                        'status'   : 'Retry available' if can_retry_now else 'Passed',
                        'can_retry': can_retry_now
                    })
                else:
                    exam_data.update({
                        'status'   : 'Retry available' if can_retry_now else 'Failed',
                        'can_retry': can_retry_now
                    })

                # 6b) Re-check “Access Required” on retry
                if exam_data['status'] == 'Retry available':
                    latest_req = (
                        ExamAccessRequest.query
                        .filter_by(user_id=user_id, exam_id=exam.id, status='approved')
                        .order_by(ExamAccessRequest.requested_at.desc())
                        .first()
                    )
                    if not latest_req or latest_req.used:
                        exam_data['status']      = 'Access Required'
                        exam_data['can_request'] = True
                        exam_data['can_retry']   = False

            # 7) LEVEL PROMOTION BADGE
            if exam_data['status'] == 'Passed':
                if check_level_completion(current_user.id, exam.level_id):
                    exam_data['status'] = 'Level Completed'

            processed_exams.append(exam_data)

        # ── Special Exam Papers ───────────────────────────────────────
        from utils.special_exams import special_paper_ids
        p1_id, p2_id = special_paper_ids(user_tenant_id())
        record = SpecialExamRecord.query.filter_by(user_id=user_id).first()

        def can_attempt_special(completed_at, retry_delta):
            return not completed_at or (now >= (completed_at + retry_delta))

        # Paper 1
        if record and record.paper1_passed:
            next_try  = record.paper1_completed_at + special_retry_p1
            p1_status = 'Retry available' if (now >= next_try) else 'Passed'
        elif record:
            if record.paper2_passed:
                p1_status = 'Locked (Paper 2 passed)'
            elif record.paper1_completed_at:
                p1_status = 'Retry available' if can_attempt_special(record.paper1_completed_at, special_retry_p1) else 'Failed'
            else:
                p1_status = 'Start Exam'
        else:
            p1_status = 'Start Exam'

        paper1_data = {
            'exam_id'    : p1_id,
            'title'      : 'Special Exam Paper 1',
            'category'   : 'Special',
            'duration'   : 60,
            'status'     : p1_status,
            'retry_date' : (
                (record.paper1_completed_at + special_retry_p1).date().isoformat()
                if (record and record.paper1_completed_at) else None
            ),
            'can_retry'  : (p1_status in ('Start Exam', 'Retry available')),
            'attempts'   : (getattr(record, 'paper1_attempts', 0) if record else 0),
            'route'      : 'special_exams_routes.exam_paper1'
        }

        # Paper 2
        if record and record.paper2_passed:
            next_try  = record.paper2_completed_at + special_retry_p2
            p2_status = 'Retry available' if (now >= next_try) else 'Passed'
        elif record:
            if record.paper1_passed:
                p2_status = 'Locked (Paper 1 passed)'
            elif record.paper2_completed_at:
                p2_status = 'Retry available' if can_attempt_special(record.paper2_completed_at, special_retry_p2) else 'Failed'
            else:
                p2_status = 'Start Exam'
        else:
            p2_status = 'Start Exam'

        paper2_data = {
            'exam_id'    : p2_id,
            'title'      : 'Special Exam Paper 2',
            'category'   : 'Special',
            'duration'   : 60,
            'status'     : p2_status,
            'retry_date' : (
                (record.paper2_completed_at + special_retry_p2).date().isoformat()
                if (record and record.paper2_completed_at) else None
            ),
            'can_retry'  : (p2_status in ('Start Exam', 'Retry available')),
            'attempts'   : (getattr(record, 'paper2_attempts', 0) if record else 0),
            'route'      : 'special_exams_routes.exam_paper2'
        }

        # Enforce access gating on special papers
        for paper in (paper1_data, paper2_data):
            if paper['status'] in ('Start Exam', 'Retry available'):
                latest_req = (
                    ExamAccessRequest.query
                    .filter_by(user_id=user_id, exam_id=paper['exam_id'])
                    .order_by(ExamAccessRequest.requested_at.desc())
                    .first()
                )
                if not latest_req or latest_req.status != 'approved' or latest_req.used:
                    paper['status']      = 'Access Required'
                    paper['can_retry']   = False
                    if not latest_req or latest_req.status == 'rejected' or latest_req.used:
                        paper['can_request'] = True
                    else:
                        paper['can_request'] = False

        unlocked_level = session.pop("new_level_unlocked", None)
        if current_user.designation_id != 1:
            unlocked_level = None

        return render_template(
            'exam_list.html',
            exams          = processed_exams,
            special_exams  = [paper1_data, paper2_data],
            message        = f"Found {len(processed_exams)} regular exams",
            unlocked_level = unlocked_level
        )

    except SQLAlchemyError as e:
        logging.critical(f"Database error in list_exams: {e}")
        db.session.rollback()
        return render_template('500.html', error="Exam data unavailable"), 500

    except TemplateNotFound as e:
        logging.error(f"Missing template: {e}")
        return "System error: Display template missing", 500

    except Exception as e:
        logging.error(f"Unexpected error in list_exams: {e}")
        return render_template('500.html', error="Failed to load exam list"), 500


# ---------------------------------------
# Update Level Progression Function
# ---------------------------------------
def update_level_progression(user_id, exam_id):
    """
    Update the user's level progression after an exam attempt.
    Handles:
      - Score and attempt tracking
      - Status updates for Level-Area completion
      - Level advancement logic
      - Designation-based skipping
    """
    try:
        exam = Exam.query.get(exam_id)
        user = User.query.get(user_id)
        if not exam or not user:
            return  # nothing to do if either is missing

        # 1) Find existing progression for this user/level/area
        existing_progress = UserLevelProgress.query.filter_by(
            user_id=user_id,
            level_id=exam.level_id,
            area_id=exam.area_id
        ).first()

        # 2) Grab the user's latest score record for this exact exam
        latest_score = UserScore.query.filter_by(
            user_id=user_id,
            exam_id=exam.id
        ).order_by(UserScore.created_at.desc()).first()
        if not latest_score:
            return  # no score to evaluate

        # 3) If no UserLevelProgress row, create one
        if not existing_progress:
            existing_progress = UserLevelProgress(
                user_id=user_id,
                level_id=exam.level_id,
                category_id=exam.category_id,
                area_id=exam.area_id,
                attempts=0,
                best_score=0,
                status='pending'
            )
            db.session.add(existing_progress)

        # 4) Update attempts and best_score
        existing_progress.attempts += 1
        existing_progress.best_score = max(
            existing_progress.best_score or 0,
            latest_score.score
        )
        # 5) If they passed (>=56), mark this Level-Area as 'completed'
        if latest_score.score >= get_passing_score(exam):
            existing_progress.status = 'completed'

        db.session.commit()

        # 6) If the entire level is done (all areas)—advance user
        unlocked = advance_user_level_after_completion(user_id, exam.level_id)
        if unlocked:
            flash(
                f"Congratulations! You have unlocked Level {unlocked}",
                "success"
            )

    except SQLAlchemyError as e:
        logging.error(f"Database error in update_level_progression: {e}")
        db.session.rollback()
    except Exception as e:
        logging.error(f"Unexpected error in update_level_progression: {e}")

# ------------------------------------------------------------
# helper sits first, so linters see it before it’s used
# ------------------------------------------------------------
def calculate_grade_for_exam(percentage: float, exam=None) -> str:
    return grade_by_threshold(percentage, get_passing_score(exam) if exam else None)

# ------------------------------------------------------------
# Route to submit an exam
# ------------------------------------------------------------
@exams_routes.route("/<int:exam_id>/submit", methods=["POST"])
@login_required
def submit_exam(exam_id):
    """
    Score an exam attempt, enforce time + retake rules, and record the result,
    plus log any incorrect answers.
    """
    try:
        # 1) Load exam and form data
        exam      = Exam.query.options(db.joinedload(Exam.category)).get_or_404(exam_id)
        assert_tenant_access(exam)
        submitted = request.form

        if not can_access_exam_level(current_user, exam):
            flash("Your level is not high enough to take this exam yet.", "warning")
            return redirect(url_for("exams_routes.list_exams"))

        passing = get_passing_score(exam)

        # 2) Block if user already passed
        existing = UserScore.query.filter_by(user_id=current_user.id, exam_id=exam_id).first()
        if existing and existing.score >= passing:
            flash("You have already passed this exam.", "info")
            return redirect(url_for("exams_routes.list_exams"))

        # 3) Check duration
        start_time = datetime.fromisoformat(submitted.get("start_time"))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        end_time = datetime.now(timezone.utc)
        if (end_time - start_time).total_seconds() / 60 > exam.duration:
            flash("Exam duration exceeded.", "danger")
            return redirect(url_for("exams_routes.start_exam", exam_id=exam_id))

        # 4) Collect served questions
        served_ids = [int(qid) for qid in submitted.get("served_questions", "").split(",") if qid]
        questions  = Question.query.filter(Question.id.in_(served_ids)).all()
        if not questions:
            flash("No valid questions found for scoring.", "danger")
            return redirect(url_for("exams_routes.start_exam", exam_id=exam_id))

        # 5) Calculate score
        score = grade_exam(questions, submitted, exam=exam)
        passed = exam_passed(score, exam)
        grade  = calculate_grade_for_exam(score, exam)

        # 6) ProctorIQ trust score
        import json as _json
        from utils.local_ai import proctoriq_assess
        proctor_raw = submitted.get("proctor_events", "{}")
        try:
            proctor_events = _json.loads(proctor_raw) if proctor_raw else {}
        except _json.JSONDecodeError:
            proctor_events = {}
        proctor_events["time_spent_seconds"] = int(submitted.get("time_spent", 0) or 0)
        proctor_events["expected_time_seconds"] = exam.duration * 60
        trust_score, proctor_narrative = proctoriq_assess(proctor_events, exam.title)

        # 7) Save / update UserScore
        if existing:
            if existing.score < passing:
                if score > existing.score:
                    existing.score = score
                existing.attempts += 1
                existing.area_id  = exam.area_id
                existing.level_id = exam.level_id
            existing.trust_score = trust_score
            existing.proctor_events = _json.dumps(proctor_events)
            existing.proctor_narrative = proctor_narrative
        else:
            new_score = UserScore(
                user_id     = current_user.id,
                exam_id     = exam_id,
                area_id     = exam.area_id,
                level_id    = exam.level_id,
                category_id = exam.category_id,
                score       = score,
                attempts    = 1,
                trust_score = trust_score,
                proctor_events = _json.dumps(proctor_events),
                proctor_narrative = proctor_narrative,
                created_at  = end_time
            )
            db.session.add(new_score)

        # ─── Record each incorrect answer ─────────────────────────
        # Clear any prior logs for this exam attempt
        IncorrectAnswer.query \
            .filter_by(
                user_id       = current_user.id,
                exam_id       = exam_id,
                special_paper = None
            ) \
            .delete(synchronize_session=False)

        # Insert a row for each wrong question
        for q in questions:
            q_score = score_question(q, submitted)
            if q_score < 100:
                user_ans = submitted.get(f"answers[{q.id}]", "")
                if hasattr(submitted, "getlist"):
                    multi = submitted.getlist(f"answers[{q.id}]")
                    if multi:
                        user_ans = ",".join(multi)
                db.session.add(IncorrectAnswer(
                    user_id        = current_user.id,
                    exam_id        = exam_id,
                    special_paper  = None,
                    question_id    = q.id,
                    user_answer    = str(user_ans),
                    correct_answer = q.correct_answer,
                    answered_at    = end_time
                ))

        # Commit both score + incorrect‐answer logs in one transaction
        db.session.commit()

        # Clear active exam session
        session.pop('active_exam', None)

        update_level_progression(current_user.id, exam_id)
        
        # 7) Flash result and go to dashboard
        flash(
            f"You scored {score:.2f}% ({grade}) on “{exam.title}”",
            "success" if passed else "warning"
        )
        return redirect(url_for("exams_routes.exam_results"))

    except SQLAlchemyError as e:
        db.session.rollback()
        logging.error(f"DB error in submit_exam: {e}")
        flash("Failed to save results.", "danger")
        return redirect(url_for("exams_routes.start_exam", exam_id=exam_id))

    except ValueError as ve:
        logging.error(f"Bad data in submit_exam: {ve}")
        flash("Invalid exam data.", "danger")
        return redirect(url_for("exams_routes.list_exams"))

    except Exception as ex:
        logging.error(f"Unexpected error in submit_exam: {ex}")
        flash("Exam processing failed.", "danger")
        return redirect(url_for("exams_routes.list_exams"))

# -------------------------------
# Exam Results 
# -------------------------------
@exams_routes.route("/results", methods=["GET"])
@login_required
def exam_results():
    """
    Results dashboard:
        • every regular exam (even if never attempted)
        • special papers 1 & 2
        • latest attempt determines status
    """
    try:
        tid = user_tenant_id()
        special_retry_p1 = special_exam_retry_period(tid, 1)
        special_retry_p2 = special_exam_retry_period(tid, 2)

        # ---------- fetch latest attempt for each regular exam ----------
        latest_scores = {
            s.exam_id: s
            for s in (
                UserScore.query
                .filter_by(user_id=current_user.id)
                .order_by(UserScore.created_at.desc())      # latest first
            )
        }

        # include exam metadata so un‑attempted rows render
        tid = user_tenant_id()
        exam_q = Exam.query.options(db.joinedload(Exam.category))
        if tid:
            exam_q = exam_q.filter(Exam.tenant_id == tid)
        all_exams = exam_q.order_by(Exam.title.asc()).all()

        normal_results = []
        for exam in all_exams:
            s = latest_scores.get(exam.id)
            ps = get_passing_score(exam)
            if s:
                passed = s.score >= ps
                grade = calculate_grade_for_exam(s.score, exam)
                integrity = getattr(s, "trust_score", None)
                eligible = passed and check_level_completion(current_user.id, exam.level_id) if passed else False
                retry_date = None
                if not passed:
                    retry_date = (
                        (s.created_at + exam_retry_period(exam)).strftime("%Y-%m-%d")
                        if s.created_at else None
                    )
                normal_results.append({
                    "exam_title": exam.title,
                    "category"  : exam.category.name if exam.category else "General",
                    "score"     : round(s.score, 2),
                    "grade"     : grade,
                    "integrity" : round(integrity, 1) if integrity is not None else "—",
                    "status"    : "Pass" if passed else "Fail",
                    "eligible"  : "Yes" if eligible else ("—" if not passed else "No"),
                    "attempts"  : s.attempts or 1,
                    "date"      : s.created_at.strftime("%Y-%m-%d") if s.created_at else "Unknown",
                    "passed"    : passed,
                    "retry_date": retry_date or "—"
                })
            else:
                normal_results.append({
                    "exam_title": exam.title,
                    "category"  : exam.category.name if exam.category else "General",
                    "score"     : "—",
                    "grade"     : "—",
                    "integrity" : "—",
                    "status"    : "Not Attempted",
                    "eligible"  : "—",
                    "attempts"  : 0,
                    "date"      : "—",
                    "passed"    : False,
                    "retry_date": "—",
                    "not_attempted": True
                })

        # ---------- special exam papers (latest‑attempt logic) ----------
        special_results = []
        record = (
            db.session.execute(
                db.select(SpecialExamRecord).filter_by(user_id=current_user.id)
            ).scalar_one_or_none()
        )

        def add_special_row(title, score, passed, completed_at, retry_delta):
            """
            Normalise output for each special paper.
            • If never attempted (completed_at is None) ⇒ Not Attempted.
            • Else show real score / pass / fail and retry date.
            """
            if completed_at:
                retry_date = (
                    (completed_at + retry_delta).strftime("%Y-%m-%d")
                    if (not passed and completed_at) else "—"
                )
                grade = calculate_grade_for_exam(score, None)
                special_results.append({
                    "exam_title": title,
                    "category"  : "Special",
                    "score"     : round(score, 2),
                    "grade"     : grade,
                    "integrity" : "—",
                    "status"    : "Pass" if passed else "Fail",
                    "eligible"  : "—",
                    "attempts"  : 1,
                    "date"      : completed_at.strftime("%Y-%m-%d"),
                    "passed"    : passed,
                    "retry_date": retry_date
                })
            else:   # never taken
                special_results.append({
                    "exam_title": title,
                    "category"  : "Special",
                    "score"     : "—",
                    "grade"     : "—",
                    "integrity" : "—",
                    "status"    : "Not Attempted",
                    "eligible"  : "—",
                    "attempts"  : 0,
                    "date"      : "—",
                    "passed"    : False,
                    "retry_date": "—"
                })

        if record:
            add_special_row(
                "Special Exam Paper 1",
                record.paper1_score or 0,
                record.paper1_passed,
                record.paper1_completed_at,
                special_retry_p1,
            )
            add_special_row(
                "Special Exam Paper 2",
                record.paper2_score or 0,
                record.paper2_passed,
                record.paper2_completed_at,
                special_retry_p2,
            )

        # ---------- combine + render ----------
        all_results  = normal_results + special_results
        passed_count = sum(1 for r in all_results if r["passed"])
        failed_count = sum(
            1 for r in all_results
            if (not r["passed"]) and r["score"] != "—"
        )
        not_attempted_count = sum(1 for r in all_results if r["score"] == "—")

        return render_template(
            "exam_results.html",
            results           = all_results,
            total_attempts    = passed_count + failed_count,   # attempted only
            passed_count      = passed_count,
            failed_count      = failed_count,
            not_attempted_cnt = not_attempted_count            # if you display it
        )

    except Exception as e:
        logging.error(f"Error loading results for user {current_user.id}: {e}")
        flash("Could not load exam results.", "danger")
        return redirect(url_for("exams_routes.list_exams"))

# -------------------------------
# Start Exam
# -------------------------------
@exams_routes.route("/<int:exam_id>/start", methods=["GET"])
@login_required
def start_exam(exam_id):
    """
    Serve the exam page after all eligibility checks.

    • honours ‘skippable’ exams (with ?force=true override)
    • blocks users below the exam’s minimum level
    • enforces a 30-day cool-down after each failed attempt
    • prevents retake after a passing score (≥ 56 %)
    • REFUSES start unless study material for this area + level is 100 % complete
    """
    try:
        exam = (
            Exam.query
            .options(db.joinedload(Exam.category))
            .get_or_404(exam_id)
        )
        assert_tenant_access(exam)
        passing = get_passing_score(exam)
        force   = request.args.get("force", "").lower() == "true"
        now_utc = datetime.utcnow()

        # Check for active session
        active = session.get('active_exam')
        if active and active.get('exam_type') == 'regular' and active.get('exam_id') == exam_id:
            served_ids = [int(qid) for qid in active.get("served_questions", "").split(",") if qid]
            questions = Question.query.filter(Question.id.in_(served_ids)).all()
            question_map = {q.id: q for q in questions}
            selected = [question_map[qid] for qid in served_ids if qid in question_map]
            start_time_str = active.get("start_time")
            answers = active.get("answers", {})
            proctor_events = active.get("proctor_events", {})
        else:
            # ─── 1) Prerequisite Study Check (exact‐course) ────────────────────
            prog = UserProgress.query.filter_by(
                user_id=current_user.id,
                study_material_id=exam.course_id,
                completed=True
            ).first()
            if not prog:
                flash("Please finish the study material first.", "danger")
                return redirect(url_for("exams_routes.list_exams"))

            # ─── 2) Access Approval Check ────────────────────────────────────
            access_req = (
                ExamAccessRequest.query
                .filter_by(user_id=current_user.id, exam_id=exam_id, status="approved")
                .order_by(ExamAccessRequest.requested_at.desc())
                .first()
            )
            if not access_req:
                flash("You must request access and wait for admin approval before starting this exam.", "warning")
                return redirect(url_for("exams_routes.list_exams"))

            if access_req.used:
                flash("This access has already been used. Please request exam access again.", "info")
                return redirect(url_for("exams_routes.list_exams"))

            # ─── 3) Optional Skip Gate (informational only) ─────────────────
            if exam.is_skippable(current_user) and not force:
                flash(
                    "You can skip this exam. Click “Take Anyway” if you’d still like to attempt it.",
                    "info"
                )

            # ─── 4) Level Requirement ────────────────────────────────────────
            if not can_access_exam_level(current_user, exam):
                flash("Your level is not high enough to take this exam yet.", "warning")
                return redirect(url_for("exams_routes.list_exams"))

            # ─── 5) Cooldown Logic ──────────────────────────────────────────
            last_score = (
                UserScore.query
                .filter_by(user_id=current_user.id, exam_id=exam_id)
                .order_by(UserScore.created_at.desc())
                .first()
            )
            if last_score:
                if last_score.score >= passing:
                    flash("You have already passed this exam.", "info")
                    return redirect(url_for("exams_routes.list_exams"))

                next_try = last_score.created_at + exam_retry_period(exam)
                if now_utc < next_try:
                    flash(f"You can retry this exam after {next_try.strftime('%Y-%m-%d')}.", "warning")
                    return redirect(url_for("exams_routes.list_exams"))

            # ─── 6) Questions Load ──────────────────────────────────────────
            questions = Question.query.filter_by(exam_id=exam.id).all()
            if not questions:
                flash("This exam has no questions yet.", "warning")
                return redirect(url_for("exams_routes.list_exams"))

            selected = random.sample(questions, min(len(questions), 20))

            # ─── 7) Mark Access As Used ─────────────────────────────────────
            access_req.used = True
            db.session.commit()

            start_time_str = now_utc.isoformat()
            answers = {}
            proctor_events = {
                'tab_switches': 0,
                'focus_losses': 0,
                'fullscreen_escapes': 0,
                'copy_attempts': 0,
                'right_clicks': 0
            }

            # Save in session
            session['active_exam'] = {
                'exam_type': 'regular',
                'exam_id': exam_id,
                'start_time': start_time_str,
                'served_questions': ",".join(str(q.id) for q in selected),
                'answers': answers,
                'proctor_events': proctor_events
            }
            session.modified = True

        from utils.exam_timer import exam_timer_context
        timer_ctx = exam_timer_context(start_time_str, exam.duration)

        return render_template(
            "exam_page.html",
            exam=exam,
            questions=[
                {
                    "id": q.id,
                    "text": q.question_text,
                    "choices": (q.choices or "").split(",") if q.choices else [],
                    "question_type": getattr(q, "question_type", None) or "single_choice",
                }
                for q in selected
            ],
            start_time=start_time_str,
            served_questions=",".join(str(q.id) for q in selected),
            answers=answers,
            proctor_events=proctor_events,
            **timer_ctx,
        )

    except Exception as err:
        logging.exception(f"Exam start error: {err}")
        flash("Could not start exam.", "danger")
        return redirect(url_for("exams_routes.list_exams"))


# -------------------------------
# Debug Start Exam Route
# -------------------------------
@exams_routes.route("/debug/start/<int:exam_id>", methods=["GET"])
@login_required
def debug_start_exam(exam_id):
    """
    Debug route to test the start_exam logic without admin approval,
    but STILL enforces the study‐completion and other guards.
    Disabled in production unless ALLOW_DEBUG_EXAM=1.
    """
    import os
    from flask import abort

    if os.getenv("FLASK_ENV", "").lower() == "production" and not os.getenv("ALLOW_DEBUG_EXAM"):
        abort(404)
    try:
        exam = Exam.query.get_or_404(exam_id)
        assert_tenant_access(exam)
        passing = get_passing_score(exam)

        # ─── 1) Prerequisite Study Check (exact‐course) ───────────────────
        prog = UserProgress.query.filter_by(
            user_id=current_user.id,
            study_material_id=exam.course_id,
            completed=True
        ).first()
        if not prog:
            flash("Please finish the study material first.", "danger")
            return redirect(url_for("exams_routes.list_exams"))

        # ─── 2) Level Requirement ───────────────────────────────────────
        if not can_access_exam_level(current_user, exam):
            flash("Your level is not high enough to take this exam yet.", "warning")
            return redirect(url_for("exams_routes.list_exams"))

        # ─── 3) Cooldown Logic (same as above) ──────────────────────────
        last_score = (
            UserScore.query
            .filter_by(user_id=current_user.id, exam_id=exam_id)
            .order_by(UserScore.created_at.desc())
            .first()
        )
        if last_score:
            if last_score.score >= passing:
                flash("You have already passed this exam.", "info")
                return redirect(url_for("exams_routes.list_exams"))

            next_try = last_score.created_at + exam_retry_period(exam)
            if datetime.utcnow() < next_try:
                flash(f"You can retry this exam after {next_try.strftime('%Y-%m-%d')}.", "warning")
                return redirect(url_for("exams_routes.list_exams"))

        # ─── 4) Load all questions (no admin‐approval check) ─────────────
        questions = Question.query.filter_by(exam_id=exam.id).all()
        if not questions:
            flash("This exam has no questions yet.", "warning")
            return redirect(url_for("exams_routes.list_exams"))

        debug_data = {
            "exam": {"id": exam.id, "title": exam.title, "duration": exam.duration},
            "questions": []
        }
        for question in questions:
            # Parse choices string into a list
            choices_list = (
                [c.strip() for c in question.choices.split(",")]
                if isinstance(question.choices, str)
                else question.choices
            )
            debug_data["questions"].append({
                "id": question.id,
                "text": question.question_text,
                "choices": choices_list
            })

        return jsonify(debug_data)

    except SQLAlchemyError as e:
        logging.error(f"Database error in debug_start_exam for Exam ID {exam_id}: {e}")
        return jsonify({"error": "Database error occurred"}), 500

    except Exception as e:
        logging.error(f"Unexpected error in debug_start_exam for Exam ID {exam_id}: {e}")
        return jsonify({"error": "Unexpected error occurred"}), 500


# -------------------------------
# Route to Fetch Dropdown Data for Exam Creation
# -------------------------------
@exams_routes.route('/get_exam_dropdowns', methods=['GET'])
@login_required
def get_exam_dropdowns():
    """
    Fetch Levels, Categories, Designation Levels, Courses, and Areas for Exam Creation.
    This route is called via AJAX to populate the dropdowns dynamically.
    """
    try:
        # Query each table
        levels       = tenant_levels_query().order_by(Level.level_number.asc()).all()
        categories   = tenant_categories_query().order_by(Category.id.asc()).all()
        designations = tenant_designations_query().order_by(Designation.id.asc()).all()
        courses      = tenant_courses_query().order_by(StudyMaterial.id.asc()).all()
        areas        = tenant_areas_query().order_by(Area.name.asc()).all()

        # Format into JSON‑serializable lists
        dropdown_data = {
            "levels": [
                {"id": lvl.id, "level_number": lvl.level_number}
                for lvl in levels
            ],
            "categories": [
                {"id": cat.id, "name": cat.name}
                for cat in categories
            ],
            "designations": [
                {"id": des.id, "title": des.title}
                for des in designations
            ],
            "courses": [
                {"id": crs.id, "title": crs.title}
                for crs in courses
            ],
            "areas": [
                {"id": area.id, "name": area.name}
                for area in areas
            ]
        }

        return jsonify(dropdown_data), 200

    except Exception as e:
        logging.error(f"Error fetching dropdown data for exams: {e}")
        return jsonify({'error': 'Failed to load dropdowns.'}), 500


@exams_routes.route('/<int:exam_id>/request_access', methods=['POST'])
@login_required
def request_exam_access(exam_id):
 
    exam = Exam.query.get_or_404(exam_id)
    assert_tenant_access(exam)

    # ─── 1) Prerequisite Study Check (exact‐course) ───────────────────
    prog = UserProgress.query.filter_by(
        user_id=current_user.id,
        study_material_id=exam.course_id,
        completed=True
    ).first()
    if not prog:
        flash("Complete the course before requesting access.", "warning")
        return redirect(url_for('exams_routes.list_exams'))

    now = datetime.utcnow()

    # ─── 2) Most Recent Score Check ─────────────────────────────────
    score_record = (
        UserScore.query
        .filter_by(user_id=current_user.id, exam_id=exam_id)
        .order_by(UserScore.created_at.desc())
        .first()
    )
    if score_record and score_record.score >= get_passing_score(exam):
        flash("You already passed this exam.", "info")
        return redirect(url_for('exams_routes.list_exams'))

    # ─── 3) Recent Access‐Request History ────────────────────────────
    recent_requests = (
        ExamAccessRequest.query
        .filter_by(user_id=current_user.id, exam_id=exam_id)
        .order_by(ExamAccessRequest.requested_at.desc())
        .all()
    )
    latest = recent_requests[0] if recent_requests else None
    recent_count = sum(1 for r in recent_requests if r.requested_at > now - timedelta(days=1))

    if latest and latest.status == 'pending':
        flash("Access already requested and is pending approval.", "info")
        return redirect(url_for('exams_routes.list_exams'))

    if latest and latest.status == 'approved' and (not score_record or score_record.score < get_passing_score(exam)):
        # User must re-request: create new request, then flash exactly this message
        new_request = ExamAccessRequest(
            user_id=current_user.id,
            exam_id=exam_id,
            status='pending',
            requested_at=now
        )
        db.session.add(new_request)
        db.session.commit()
        from utils.notifications import notify_tenant_super_admins
        if current_user.tenant_id:
            notify_tenant_super_admins(
                current_user.tenant_id,
                "New exam access request",
                f"{current_user.first_name} requested a retry for {exam.title}.",
                category="exam",
                link_url=url_for("admin_routes.manage_exam_requests"),
                icon="file-alt",
            )

        flash("You must re-request access to retry this exam.", "warning")
        return redirect(url_for('exams_routes.list_exams'))

    if recent_count >= 3:
        flash("Too many requests in the past 24 hours. Try again later.", "warning")
        return redirect(url_for('exams_routes.list_exams'))

    # ─── 4) Submit New Access Request ────────────────────────────────
    new_request = ExamAccessRequest(
        user_id=current_user.id,
        exam_id=exam_id,
        status='pending',
        requested_at=now
    )
    db.session.add(new_request)
    db.session.commit()

    from utils.notifications import notify_tenant_super_admins
    if current_user.tenant_id:
        notify_tenant_super_admins(
            current_user.tenant_id,
            "New exam access request",
            f"{current_user.first_name} {current_user.last_name} requested access to {exam.title}.",
            category="exam",
            link_url=url_for("admin_routes.manage_exam_requests"),
            icon="file-alt",
        )

    flash("Access request sent to admin.", "success")
    print(f"[ACCESS] New access request submitted — user_id={current_user.id}, exam_id={exam_id}")

    return redirect(url_for('exams_routes.list_exams'))


# -------------------------------
# AJAX Exam Autosave Routes
# -------------------------------
@exams_routes.route("/save_answer", methods=["POST"])
@login_required
def save_answer():
    try:
        data = request.get_json() or {}
        question_id = str(data.get("question_id"))
        answer = data.get("answer")
        
        if 'active_exam' not in session:
            return jsonify({"status": "error", "message": "No active exam session"}), 400
            
        session['active_exam']['answers'][question_id] = answer
        session.modified = True
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"Error in save_answer: {e}")
        return handle_api_exception(e, user_message="Could not process request.")

@exams_routes.route("/log_violation", methods=["POST"])
@login_required
def log_violation():
    try:
        data = request.get_json() or {}
        violation_type = data.get("violation_type") # e.g. 'tab_switches', 'blur_events'
        
        if 'active_exam' not in session:
            return jsonify({"status": "error", "message": "No active exam session"}), 400
            
        events = session['active_exam']['proctor_events']
        if violation_type in events:
            events[violation_type] += 1
        else:
            events[violation_type] = 1
        session.modified = True
        return jsonify({"status": "success", "count": events[violation_type]})
    except Exception as e:
        logging.error(f"Error in log_violation: {e}")
        return handle_api_exception(e, user_message="Could not process request.")
