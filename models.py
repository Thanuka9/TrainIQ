import uuid
import random
from datetime import datetime, timedelta
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Column, text, Text, Integer, String, LargeBinary, Date, DateTime, Boolean, ForeignKey, Text, Table, JSON, Index, UniqueConstraint
from sqlalchemy.orm import relationship, validates
from flask_login import UserMixin
from sqlalchemy import Float
from flask import request
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP

# -------------------------------
# Association Table for User and Tasks
# -------------------------------
user_task_association = Table(
    'user_task_association', db.Model.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('task_id', Integer, ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
)

# -------------------------------
# Association Table for Departments
# -------------------------------
user_departments = Table(
    'user_departments', db.Model.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('department_id', Integer, ForeignKey('departments.id', ondelete='CASCADE'), primary_key=True),
)

# -------------------------------------
# Association Table for Roles
# -------------------------------------
user_roles = Table(
    'user_roles', db.Model.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
)

# -------------------------------------
# Association Table for user_clients
# -------------------------------------
user_clients = Table(
  'user_clients', db.Model.metadata,
  Column('user_id',   Integer, ForeignKey('users.id', ondelete='CASCADE'),   primary_key=True),
  Column('client_id', Integer, ForeignKey('clients.id', ondelete='CASCADE'), primary_key=True),
)

# -------------------------------------
# Tenant Model
# -------------------------------------
class Tenant(db.Model):
    __tablename__ = 'tenants'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    allowed_domain = Column(String(200), nullable=True)
    logo_filename = Column(String(200), nullable=True)
    logo_data = Column(LargeBinary, nullable=True)
    logo_mimetype = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Customizable fields
    primary_color = Column(String(7), nullable=True, default="#4f46e5")
    secondary_color = Column(String(7), nullable=True, default="#06b6d4")
    support_email = Column(String(120), nullable=True, default="support@trainiq.com")
    portal_tagline = Column(String(255), nullable=True, default="Centralized HR and Performance Hub")
    enable_2fa = Column(Boolean, nullable=False, default=False)
    enable_proctoring = Column(Boolean, nullable=False, default=True)
    office_key = Column(String(50), unique=True, nullable=True)

    # SaaS subscription / limits
    plan = Column(String(50), nullable=False, default="trial")
    status = Column(String(30), nullable=False, default="trial")  # active, trial, suspended, expired
    max_users = Column(Integer, nullable=False, default=10)
    max_storage_mb = Column(Integer, nullable=False, default=2048)
    trial_ends_at = Column(DateTime, nullable=True)
    trial_reminder_7d_at = Column(DateTime, nullable=True)
    trial_reminder_1d_at = Column(DateTime, nullable=True)
    onboarding_welcome_at = Column(DateTime, nullable=True)
    onboarding_drip_1_at = Column(DateTime, nullable=True)
    onboarding_drip_3_at = Column(DateTime, nullable=True)
    onboarding_drip_7_at = Column(DateTime, nullable=True)
    billing_email = Column(String(120), nullable=True)
    billing_cycle = Column(String(20), nullable=False, default="monthly")
    stripe_customer_id = Column(String(120), nullable=True)
    stripe_subscription_id = Column(String(120), nullable=True)
    billing_period_start = Column(DateTime, nullable=True)
    billing_period_end = Column(DateTime, nullable=True)
    custom_mrr_cents = Column(Integer, nullable=True)  # CEO override for enterprise MRR (USD cents)
    enable_invite_only = Column(Boolean, nullable=False, default=False)
    suspended_at = Column(DateTime, nullable=True)
    suspended_reason = Column(Text, nullable=True)

    # Enterprise SSO (OIDC)
    sso_enabled = Column(Boolean, nullable=False, default=False)
    sso_provider = Column(String(30), nullable=True)  # google, microsoft, oidc
    sso_client_id = Column(String(255), nullable=True)
    sso_client_secret = Column(String(512), nullable=True)
    sso_issuer_url = Column(String(512), nullable=True)
    sso_tenant_domain = Column(String(255), nullable=True)  # Azure AD tenant id or domain

    invites = relationship("TenantInvite", back_populates="tenant", cascade="all, delete-orphan")

    @validates('office_key')
    def _normalize_office_key(self, _key, value):
        from utils.tenant_utils import normalize_office_key
        return normalize_office_key(value)
# -------------------------------------
class Role(db.Model):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)

    # Relationship: Users assigned to this role
    users = relationship("User", secondary=user_roles, back_populates="roles")

    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}')>"
    
# -------------------------------------
# Designation Model (Enhanced)
# -------------------------------------
class Designation(db.Model):
    __tablename__ = 'designations'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'title', name='uq_designation_tenant_title'),
    )

    id = Column(Integer, primary_key=True)
    title = Column(String(50), nullable=False)
    starting_level = Column(Integer, default=0)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant = relationship("Tenant", backref=db.backref("designations", lazy=True))

    # Relationships
    users = relationship("User", back_populates="designation")

    def can_skip_level(self, target_level):
        """Check if the user can skip a level based on their designation."""
        return self.starting_level >= target_level

    def __repr__(self):
        return f"<Designation(id={self.id}, title='{self.title}', starting_level={self.starting_level})>"

# -------------------------------------
# Category Model (Integrated)
# -------------------------------------
class Category(db.Model):
    __tablename__ = 'categories'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'name', name='uq_category_tenant_name'),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant = relationship("Tenant", backref=db.backref("categories", lazy=True))

    # Relationships
    level_areas = relationship("LevelArea", back_populates="category")
    exams = relationship("Exam", back_populates="category", cascade="all, delete-orphan")
    user_scores = relationship("UserScore", back_populates="category", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="category", cascade="all, delete-orphan")
    study_materials = relationship("StudyMaterial", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Category(id={self.id}, name='{self.name}')>"

# -------------------------------
# Client Model
# -------------------------------

class Client(db.Model):
    __tablename__ = 'clients'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'name', name='uq_client_tenant_name'),
    )

    id   = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant = relationship("Tenant", backref=db.backref("clients", lazy=True))

    # Many-to-many relationship to User
    users = relationship(
        "User",
        secondary=user_clients,
        back_populates="clients"
    )

    # One-to-many relationship to Task
    tasks = relationship(
        "Task",
        back_populates="client",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Client(id={self.id}, name='{self.name}')>"


# -------------------------------------
# Updated StudyMaterial Model
# -------------------------------------
class StudyMaterial(db.Model):
    __tablename__ = 'study_materials'

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    course_time = Column(Integer, nullable=False)
    max_time = Column(Integer, nullable=False)
    total_pages = Column(Integer, nullable=True, default=0)
    # store file IDs as a list of strings
    files = Column(ARRAY(String), default=[])
    # Unified media catalog: documents, uploaded videos, YouTube/Drive links, transcripts
    media_assets = Column(JSONB, default=list)

    # minimum_level now a simple integer gate (default = 1)
    minimum_level = Column(Integer, nullable=False, default=1)

    # Foreign Keys
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    level_id    = Column(Integer, ForeignKey('levels.id'), nullable=True)
    tenant_id   = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant      = relationship("Tenant", backref=db.backref("study_materials", lazy=True))

    # Relationships
    category      = relationship("Category", back_populates="study_materials")
    level         = relationship("Level", back_populates="study_materials")
    subtopics     = relationship("SubTopic", back_populates="study_material", cascade="all, delete-orphan")
    user_progress = relationship("UserProgress", back_populates="study_material", cascade="all, delete-orphan")
    exams         = relationship("Exam", back_populates="course", cascade="all, delete-orphan")

    def is_accessible(self, user):
        """Delegate to shared level access helper."""
        from utils.level_access import can_access_study_material
        return can_access_study_material(user, self)

    def __repr__(self):
        return f"<StudyMaterial(id={self.id}, title='{self.title}')>"


# -------------------------------------
# Updated SubTopic Model
# -------------------------------------
class SubTopic(db.Model):
    __tablename__ = 'subtopics'

    id = Column(Integer, primary_key=True)
    study_material_id = Column(Integer, ForeignKey('study_materials.id'), nullable=False)
    title = Column(String(255), nullable=False)
    # Allow NULL if a subtopic has no file
    file_id = Column(String(255), nullable=True)
    page_count = Column(Integer, nullable=True, default=0)

    # Two‑way relationship with StudyMaterial
    study_material = relationship("StudyMaterial", back_populates="subtopics")

    def __repr__(self):
        return f"<SubTopic(id={self.id}, title='{self.title}', page_count={self.page_count})>"
# -------------------------------------
# UserProgress Model
# -------------------------------------
class UserProgress(db.Model):
    __tablename__ = 'user_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    study_material_id = db.Column(db.Integer, db.ForeignKey('study_materials.id'), nullable=False, index=True)
    pages_visited = db.Column(db.Integer, default=0)  # Pages visited by the user
    progress_percentage = db.Column(db.Integer, default=0)  # Progress percentage
    time_spent = db.Column(db.Integer, default=0)  # Total time spent (in seconds)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)  # Automatic start date
    completion_date = db.Column(db.DateTime, nullable=True)
    completed = db.Column(db.Boolean, default=False)  # New field for completion status
    asset_progress = db.Column(JSONB, default=dict)  # per-asset completion % keyed by asset id

    # New Addition: Link Progress to Levels
    level_id = db.Column(db.Integer, db.ForeignKey('levels.id'), nullable=True, index=True)

    # Relationships
    user = db.relationship("User", back_populates="study_progress", passive_deletes=True)
    study_material = db.relationship("StudyMaterial", back_populates="user_progress")
    level = db.relationship("Level", back_populates="user_progress")  # New relationship

    def calculate_progress(self, total_pages):
        """Calculate and update progress percentage."""
        self.progress_percentage = int((self.pages_visited / total_pages) * 100)
        self.completed = (self.progress_percentage >= 100)  # Mark as completed if 100%
        db.session.commit()

    def update_time_spent(self, additional_time):
        """Update the total time spent on the material."""
        self.time_spent = (self.time_spent or 0) + additional_time
        db.session.commit()

    def __repr__(self):
        return (f"<UserProgress(id={self.id}, user_id={self.user_id}, "
                f"progress_percentage={self.progress_percentage}, time_spent={self.time_spent}, "
                f"completed={self.completed})>")


# -------------------------------------
# CourseNote Model — learner notes per asset/page
# -------------------------------------
class CourseNote(db.Model):
    __tablename__ = 'course_notes'
    __table_args__ = (
        UniqueConstraint(
            'user_id', 'study_material_id', 'asset_id', 'page_num',
            name='uq_course_note_scope',
        ),
        Index('ix_course_notes_user_material', 'user_id', 'study_material_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    study_material_id = db.Column(db.Integer, db.ForeignKey('study_materials.id', ondelete='CASCADE'), nullable=False, index=True)
    asset_id = db.Column(db.String(255), nullable=False, default='')
    page_num = db.Column(db.Integer, nullable=False, default=0)
    content = db.Column(db.Text, nullable=False, default='')
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('course_notes', lazy='dynamic', passive_deletes=True))
    study_material = db.relationship('StudyMaterial', backref=db.backref('course_notes', lazy='dynamic'))

    def __repr__(self):
        return f"<CourseNote user={self.user_id} material={self.study_material_id} asset={self.asset_id} page={self.page_num}>"


# -------------------------------------
# Level Model
# -------------------------------------
class Level(db.Model):
    __tablename__ = 'levels'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'level_number', name='uq_level_tenant_number'),
    )

    id = db.Column(db.Integer, primary_key=True)
    level_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)
    tenant = db.relationship("Tenant", backref=db.backref("levels", lazy=True))

    # Relationships
    level_areas = db.relationship("LevelArea", back_populates="level", cascade="all, delete-orphan")
    study_materials = db.relationship("StudyMaterial", back_populates="level", cascade="all, delete-orphan")
    user_level_progress = db.relationship("UserLevelProgress", back_populates="level", cascade="all, delete-orphan")
    user_progress = db.relationship("UserProgress", back_populates="level", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="level", cascade="all, delete-orphan")
    user_scores = relationship("UserScore", back_populates="level", cascade="all, delete-orphan") 

    def __repr__(self):
        return f"<Level(id={self.id}, level_number={self.level_number}, title='{self.title}')>"

# -------------------------------------
# UserLevelProgress Model
# -------------------------------------
class UserLevelProgress(db.Model):
    __tablename__ = 'user_level_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    level_id = db.Column(db.Integer, db.ForeignKey('levels.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    area_id = db.Column(db.Integer, ForeignKey('areas.id'), nullable=False)
    status = db.Column(db.String(20), default='pending') 
    attempts = db.Column(db.Integer, default=0)
    best_score = db.Column(db.Float)

    # Relationships
    user = db.relationship("User", back_populates="level_progress", passive_deletes=True)
    level = db.relationship("Level", back_populates="user_level_progress")
    category = db.relationship("Category")
    area = db.relationship("Area", back_populates="user_level_progress")
    

    def __repr__(self):
        return (f"<UserLevelProgress(user_id={self.user_id}, "
                f"level_id={self.level_id}, category_id={self.category_id}, "
                f"status={self.status})>")

# -------------------------------------
#User Model
# -------------------------------------
class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    phone_number = Column(String(15), nullable=True)
    employee_email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    employee_id = Column(String(20), unique=True, nullable=False)
    join_date = Column(Date, nullable=False)
    profile_picture = Column(LargeBinary, nullable=True)
    deleted_at        = Column(DateTime, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)

        # One-time privacy policy consent
    privacy_agreed = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True
    )
    privacy_agreed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )
    user_agreement_version = Column(String(20), nullable=True, index=True)
    user_agreement_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Using a relationship to link to the Department model
    departments = relationship(
        "Department",
        secondary=user_departments,
        back_populates="users"
    )

    is_super_admin = Column(Boolean, default=False)  # Super admin privileges
    is_platform_staff = Column(Boolean, default=False, nullable=False)
    platform_staff_role = Column(String(30), nullable=True)  # support, ops, admin, ceo
    admin_permissions = Column(JSON, nullable=True)  # {grants:[], denies:[], preset:str}
    trial_checklist_dismissed = Column(Boolean, default=False, nullable=False)
    current_level = Column(Integer, default=1)  # Tracks the user's current active level

    # ---------------------------------
    # Foreign Key Relationships
    # ---------------------------------
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant = relationship("Tenant", backref=db.backref("users", lazy=True))

    designation_id = Column(Integer, ForeignKey('designations.id'), nullable=True)
    designation = relationship("Designation", back_populates="users")

    clients = relationship(
    "Client",
    secondary=user_clients,
    back_populates="users",
    passive_deletes=True
    )

    # ---------------------------------
    # Progress Tracking Relationships
    # ---------------------------------
    level_progress = db.relationship(
        "UserLevelProgress",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    study_progress = db.relationship(
        "UserProgress",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    scores = db.relationship(
        "UserScore",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # ---------------------------------
    # Audit Log Relationships
    # ---------------------------------
    audit_logs = relationship(
    'AuditLog',
    back_populates='actor_user',
    cascade='all, delete-orphan',
    passive_deletes=True
    )

    # ---------------------------------
    # Exam and Task Management
    # ---------------------------------
    created_exams = relationship(
        "Exam",
        back_populates="created_by_user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    tasks_assigned = relationship(
        "Task",
        foreign_keys='Task.assigned_by',
        back_populates="assigned_by_user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    tasks_received = relationship(
        "Task",
        secondary="user_task_association",
        back_populates="assignees",
        passive_deletes=True
    )
    # ---------------------------------
    # password_reset_requests
    # ---------------------------------
    password_reset_requests = db.relationship(
        'PasswordResetRequest',
        back_populates='user',
        cascade='all, delete-orphan'
    )
    # ---------------------------------
    # Event Management
    # ---------------------------------
    events = relationship(
        "Event",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    # ---------------------------------
    # Email Verification and 2FA
    # ---------------------------------
    is_verified = Column(
        Boolean,
        nullable=False,
        server_default=text('false'),
        default=False,
        index=True
    )
    verification_token = Column(
        Text,
        nullable=True
    )
    two_fa_code = Column(
        String(6),
        nullable=True
    )
    two_fa_expiration = Column(
        DateTime,
        nullable=True
    )
    totp_secret = Column(String(64), nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    # ---------------------------------
    # Password Reset Fields
    # ---------------------------------
    password_reset_token  = Column(Text, nullable=True)
    password_reset_expiration = Column(DateTime, nullable=True)

    # ---------------------------------
    # SpecialExamRecord Relationship (One-to-One)
    # ---------------------------------
    special_exam_record = db.relationship(
        "SpecialExamRecord",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )
    # ---------------------------------
    # Incorrect Answers Tracking
    # ---------------------------------
    incorrect_answers = relationship('IncorrectAnswer', back_populates='user', cascade='all, delete-orphan')

    # ---------------------------------
    # Role-based Access Control (RBAC)
    # ---------------------------------
    roles = db.relationship("Role", secondary=user_roles, back_populates="users", passive_deletes=True)

    # ---------------------------------
    # Curent Level
    # ---------------------------------
    def get_current_level(self):
        """
        Returns the user's current active level.
        Defaults to 1 if current_level is not set.
        """
        return self.current_level if self.current_level else 1

    @property
    def role(self):
        """
        Returns the user's default role.
        If roles are assigned, returns the first role's name; otherwise defaults to "member".
        """
        if self.roles and len(self.roles) > 0:
            return self.roles[0].name
        return "member"

    # ---------------------------------
    # Designation-Based Logic
    # ---------------------------------
    def can_skip_level(self, target_level: int) -> bool:
        """
        Check if the user can skip a level based on their designation.
        Higher ``starting_level`` designations may skip lower curriculum levels.
        """
        if not self.designation:
            return False
        return self.designation.can_skip_level(target_level)

    def can_skip_exam(self, exam) -> bool:
        """
        Check if the user can skip a specific exam based on their designation.
        :param exam: Exam object to check
        :return: Boolean indicating if skipping the exam is allowed
        """
        return self.can_skip_level(exam.level.level_number)

    # ---------------------------------
    # Two-Factor Authentication
    # ---------------------------------
    def generate_2fa_code(self) -> None:
        """
        Generate and set a 6-digit 2FA code valid for 5 minutes.
        """
        self.two_fa_code = str(random.randint(100000, 999999))
        self.two_fa_expiration = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()

    # ---------------------------------
    # Lockout on Failed Logins
    # ---------------------------------
    failed_login_count = Column(Integer, default=0, nullable=False)
    is_locked          = Column(Boolean, default=False, nullable=False)
    locked_at          = Column(DateTime, nullable=True)

    def lock(self):
        """Freeze the account."""
        self.is_locked = True
        self.locked_at = datetime.utcnow()
        

    def reset_lock(self):
        """Clear failed‐login counter and unlock."""
        self.failed_login_count = 0
        self.is_locked          = False
        self.locked_at          = None
        db.session.commit()
    # ---------------------------------
    # Password Management
    # ---------------------------------
    def set_password(self, password: str) -> None:
        """
        Hash and set the user's password.
        :param password: Plain text password
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """
        Verify the user's password.
        :param password: Plain text password
        :return: Boolean indicating if the password is correct
        """
        return check_password_hash(self.password_hash, password)

    # ---------------------------------
    # String Representation for Debugging
    # ---------------------------------
    def __repr__(self):
        full_name = f"{self.first_name} {self.last_name}"
        return f"<User(id={self.id}, name='{full_name}', level={self.current_level})>"

# -------------------------------
# Exam Model
# -------------------------------
class Exam(db.Model):
    __tablename__ = 'exams'

    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    duration = Column(Integer, nullable=False)
    level_id = Column(Integer, ForeignKey('levels.id'), nullable=False)
    area_id = Column(Integer, ForeignKey('areas.id'), nullable=False)
    course_id = Column(Integer, ForeignKey('study_materials.id'), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)

    # New Additions
    minimum_level = Column(Integer, nullable=True)             # Minimum level required for this exam
    minimum_designation_id = Column(Integer, nullable=True)  # Designation PK for exam skip threshold
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    passing_score = Column(Float, nullable=False, default=70.0)
    retry_cooldown_days = Column(Integer, nullable=True)  # days between attempts; default 30 in code

    # Relationships
    tenant = relationship("Tenant", backref=db.backref("exams", lazy=True))

    # Relationships
    level = relationship("Level", back_populates="exams")
    area = relationship("Area", back_populates="exams")
    created_by_user = relationship("User", back_populates="created_exams", passive_deletes=True)
    course = relationship("StudyMaterial", back_populates="exams")
    category = relationship("Category", back_populates="exams")
    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan")
    scores = relationship("UserScore", back_populates="exam", cascade="all, delete-orphan")
    level_areas = relationship(
        "LevelArea",
        back_populates="required_exam",
        foreign_keys="[LevelArea.required_exam_id]",
        cascade="all, delete-orphan"
    )


    def __repr__(self):
        level_num = self.level.level_number if self.level else 'N/A'
        area_name = self.area.name if self.area else 'N/A'
        return f"<Exam(id={self.id}, title='{self.title}', level='{level_num}', area='{area_name}')>"

    def is_accessible(self, user):
        """Check if the user meets the level requirement (progression or designation skip)."""
        from utils.level_access import can_access_exam_level
        return can_access_exam_level(user, self)

    def is_skippable(self, user):
        """
        Check if the user can skip this exam based on their designation.
        ``minimum_designation_id`` stores a Designation primary key.
        """
        if not self.minimum_designation_id or not user.designation:
            return False
        required = Designation.query.get(self.minimum_designation_id)
        if not required:
            return False
        return user.designation.starting_level >= required.starting_level

    @property
    def minimum_designation_level(self):
        """Deprecated alias — column renamed to ``minimum_designation_id``."""
        return self.minimum_designation_id

    @minimum_designation_level.setter
    def minimum_designation_level(self, value):
        self.minimum_designation_id = value

    incorrect_answers = relationship('IncorrectAnswer', back_populates='exam', cascade='all, delete-orphan')
# -------------------------------
# Question Model
# -------------------------------
class Question(db.Model):
    __tablename__ = 'questions'

    id = Column(Integer, primary_key=True)
    exam_id = Column(Integer, ForeignKey('exams.id', ondelete='CASCADE'), nullable=False)
    question_text = Column(Text, nullable=False)
    choices = Column(Text, nullable=False)  # Stores comma-separated choices
    correct_answer = Column(Text, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id', ondelete='CASCADE'), nullable=False)
    question_type = Column(String(50), nullable=False, default='single_choice')

    # Relationships
    exam = relationship("Exam", back_populates="questions", passive_deletes=True)
    category = relationship("Category", back_populates="questions", passive_deletes=True)

    def __repr__(self):
        return f"<Question(id={self.id}, text='{self.question_text[:30]}...', category='{self.category.name}')>"

    def get_choices(self):
        """Return the list of choices as a list"""
        return self.choices.split(',')
    
    def set_choices(self, choices_list):
        """Set the choices as a comma-separated string"""
        self.choices = ','.join(choices_list)

    @property
    def correct_ans(self):
        """
        Returns the letter (A, B, C, or D) corresponding to correct_answer.
        """
        try:
            choices_list = self.get_choices()
            idx = choices_list.index(self.correct_answer)
            if 0 <= idx < 4:
                return 'ABCD'[idx]
        except (ValueError, TypeError, IndexError):
            pass
        return None

    @correct_ans.setter
    def correct_ans(self, value):
        """
        Sets correct_answer based on the letter (A, B, C, or D).
        """
        try:
            choices_list = self.get_choices()
            val = value.strip().upper()
            if len(val) == 1 and 'A' <= val <= 'D':
                idx = ord(val) - ord('A')
                if 0 <= idx < len(choices_list):
                    self.correct_answer = choices_list[idx]
        except Exception:
            pass

# -------------------------------
# UserScore Model
# -------------------------------
class UserScore(db.Model):
    __tablename__ = 'user_scores'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    exam_id = Column(Integer, ForeignKey('exams.id'), nullable=False)
    area_id = Column(Integer, ForeignKey('areas.id'), nullable=False)
    level_id = Column(Integer, ForeignKey('levels.id'), nullable=False)  # Tracks Level
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    score = Column(Float, nullable=False)  # Changed from Integer to Float
    attempts = Column(Integer, default=1)  # Tracks attempts for better analytics
    trust_score = Column(Float, nullable=True)       # ProctorIQ integrity score (0-100)
    proctor_events = Column(Text, nullable=True)     # JSON blob of proctoring events
    proctor_narrative = Column(Text, nullable=True)  # AI-generated integrity assessment
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="scores", passive_deletes=True)
    exam = relationship("Exam", back_populates="scores")
    area = relationship("Area", back_populates="user_scores")  # Linked to Area
    level = relationship("Level", back_populates="user_scores")  # Linked to Level
    category = relationship("Category", back_populates="user_scores")  # Linked to Category

    def __repr__(self):
        # Handle None values gracefully in repr
        level_num = self.level.level_number if self.level else 'N/A'
        area_name = self.area.name if self.area else 'N/A'
        return (f"<UserScore(id={self.id}, user_id={self.user_id}, "
                f"level={level_num}, area='{area_name}', score={self.score})>")

# -------------------------------
# Exam Access Request Model
# -------------------------------
class ExamAccessRequest(db.Model):
    __tablename__ = 'exam_access_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False
    )
    exam_id = db.Column(db.Integer, nullable=False)  # Supports both regular & special exams
    status = db.Column(db.String(20), default='pending')  # pending | approved | rejected
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    used        = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship(
        "User",
        backref=db.backref("exam_requests", passive_deletes=True),
        passive_deletes=True
    )

    @property
    def is_special_exam(self):
        from utils.special_exams import is_special_exam_id
        return is_special_exam_id(self.exam_id)

# --------------------------------    
# Task Model
# -------------------------------
class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    status = db.Column(db.String(50), nullable=False, default="Getting Things Started...")
    progress = db.Column(db.Integer, nullable=False, default=0)

    # Foreign Keys
    assigned_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False
    )
    completed_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id', ondelete='CASCADE'), nullable=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)

    # Relationships
    tenant = db.relationship("Tenant", backref=db.backref("tasks", lazy=True))

    # Relationships
    assigned_by_user = db.relationship(
        "User",
        foreign_keys=[assigned_by],
        back_populates="tasks_assigned",
        passive_deletes=True
    )
    completed_by_user = db.relationship(
        "User",
        foreign_keys=[completed_by],
        passive_deletes=True
    )
    client = db.relationship("Client", back_populates="tasks")

    assignees = db.relationship(
        "User",
        secondary="user_task_association",
        back_populates="tasks_received"
    )

    documents = db.relationship(
        "TaskDocument",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    def calculate_progress(self):
        """Calculate progress based on the task's status."""
        status_progress_mapping = {
            "Getting Things Started...": 0,
            "Setting Up the Path...": 20,
            "Halfway There! Keep Going!": 50,
            "Almost Done! Just a Little More!": 80,
            "Wrapping Things Up...": 90,
            "Final Touches in Progress...": 95,
            "Complete! Ready to Go!": 100
        }
        self.progress = status_progress_mapping.get(self.status, 0)
        db.session.commit()

    def __repr__(self):
        return f"<Task(id={self.id}, title='{self.title}', status='{self.status}', progress={self.progress})>"

# -------------------------------
# TaskDocument Model
# -------------------------------
class TaskDocument(db.Model):
    __tablename__ = 'task_documents'

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    filetype = Column(String(255), nullable=False)
    data = Column(LargeBinary, nullable=False)
    upload_date = Column(DateTime, default=datetime.utcnow)

    # 1) add ondelete="CASCADE" here:
    task_id = Column(
        Integer,
        ForeignKey('tasks.id', ondelete='CASCADE'),
        nullable=False
    )

    # 2) enable passive_deletes=True so SQLAlchemy trusts the DB to cascade
    task = relationship(
        "Task",
        back_populates="documents",
        passive_deletes=True
    )

    def __repr__(self):
        return f"<TaskDocument(id={self.id}, filename='{self.filename}', task_id={self.task_id})>"

# -------------------------------
# FailedLogin Model
# -------------------------------
class FailedLogin(db.Model):
    __tablename__ = 'failed_logins'

    id          = Column(Integer, primary_key=True)
    email       = Column(String(120), nullable=False)
    ip_address  = Column(String(45), nullable=True)
    user_agent  = Column(String(256), nullable=True)
    timestamp   = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return (
            f"<FailedLogin(id={self.id}, email='{self.email}', "
            f"ip='{self.ip_address}', ts={self.timestamp})>"
        )

def log_failed_login_attempt(email):
    """Log a failed login attempt, capturing IP and User-Agent."""
    try:
        fl = FailedLogin(
            email=email,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            timestamp=datetime.utcnow()
        )
        db.session.add(fl)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Consider using logging.error(...) instead of print in production
        print(f"Error logging failed login attempt: {e}")

# -------------------------------
# Event Model
# -------------------------------
class Event(db.Model):
    __tablename__ = 'events'

    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    date = Column(Date, nullable=False)

    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    user = db.relationship("User", back_populates="events", passive_deletes=True)

    def __repr__(self):
        return f"<Event(id={self.id}, title='{self.title}', date={self.date}, user_id={self.user_id})>"

# -------------------------------
# Area Model
# -------------------------------
class Area(db.Model):
    __tablename__ = 'areas'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'name', name='uq_area_tenant_name'),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant = relationship("Tenant", backref=db.backref("areas", lazy=True))

    # Relationships
    level_areas = relationship("LevelArea", back_populates="area", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="area", cascade="all, delete-orphan")  # Linked to Exam
    user_level_progress = relationship("UserLevelProgress", back_populates="area", cascade="all, delete-orphan")
    user_scores = relationship("UserScore", back_populates="area", cascade="all, delete-orphan")  # Linked to UserScore

    def __repr__(self):
        return f"<Area(id={self.id}, name='{self.name}')>"

# -------------------------------
# LevelArea Model
# -------------------------------
class LevelArea(db.Model):
    __tablename__ = 'level_areas'

    id               = Column(Integer, primary_key=True)
    level_id         = Column(Integer, ForeignKey('levels.id'), nullable=False)
    category_id      = Column(Integer, ForeignKey('categories.id'), nullable=False)
    area_id          = Column(Integer, ForeignKey('areas.id'), nullable=False)
    required_exam_id = Column(Integer, ForeignKey('exams.id'), nullable=True)

    # Relationships
    level         = relationship("Level",    back_populates="level_areas")
    category      = relationship("Category", back_populates="level_areas")
    area          = relationship("Area",     back_populates="level_areas")
    required_exam = relationship(
        "Exam",
        foreign_keys=[required_exam_id],
        back_populates="level_areas",
        lazy='joined'
    )

    @property
    def exam(self):
        """Alias for backward compatibility with existing code."""
        return self.required_exam

    def __repr__(self):
        return (
            f"<LevelArea(id={self.id}, level_id={self.level_id}, "
            f"category_id={self.category_id}, area_id={self.area_id}, "
            f"required_exam_id={self.required_exam_id})>"
        )

# -------------------------------
# SpecialExamRecord Model
# -------------------------------
class SpecialExamRecord(db.Model):
    __tablename__ = 'special_exam_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # Paper 1 fields
    paper1_score = db.Column(db.Float, default=0.0)
    paper1_passed = db.Column(db.Boolean, default=False)
    paper1_time_spent = db.Column(db.Integer, default=0)  # in seconds
    paper1_completed_at = db.Column(db.DateTime, nullable=True)
    paper1_attempts = db.Column(db.Integer, default=0)

    # Paper 2 fields
    paper2_score = db.Column(db.Float, default=0.0)
    paper2_passed = db.Column(db.Boolean, default=False)
    paper2_time_spent = db.Column(db.Integer, default=0)  # in seconds
    paper2_completed_at = db.Column(db.DateTime, nullable=True)
    paper2_attempts = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    # Use back_populates on both sides of the relationship.
    user = db.relationship("User", back_populates="special_exam_record", uselist=False, passive_deletes=True)

    def __repr__(self):
        return f"<SpecialExamRecord(id={self.id}, user_id={self.user_id})>"

# -------------------------------------
# Department Model
# -------------------------------------
class Department(db.Model):
    __tablename__ = 'departments'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'name', name='uq_department_tenant_name'),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True)
    tenant = relationship("Tenant", backref=db.backref("departments", lazy=True))

    # Relationship: Users assigned to this department
    users = relationship(
        "User",
        secondary=user_departments,
        back_populates="departments"
    )
    
    def __repr__(self):
        return f"<Department(id={self.id}, name='{self.name}')>"
    
# -------------------------------------
# IncorrectAnswer Model
# -------------------------------------
class IncorrectAnswer(db.Model):
    __tablename__ = 'incorrect_answers'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    exam_id        = db.Column(db.Integer, db.ForeignKey('exams.id', ondelete='CASCADE'), nullable=True, index=True)
    special_paper  = db.Column(db.String(10), nullable=True, index=True)
    question_id    = db.Column(db.Integer, nullable=False)
    user_answer    = db.Column(Text, nullable=False)      # <-- now free-text
    correct_answer = db.Column(Text, nullable=False)      # <-- now free-text
    answered_at    = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_user_exam', 'user_id', 'exam_id'),
    )

    user = db.relationship(
        'User',
        back_populates='incorrect_answers',
        passive_deletes=True
    )
    exam = db.relationship(
        'Exam',
        back_populates='incorrect_answers',
        passive_deletes=True
    )

# -------------------------------------
# TenantInvite Model
# -------------------------------------
class PlatformStaffInvite(db.Model):
    __tablename__ = "platform_staff_invites"

    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, index=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    role = Column(String(30), nullable=False, default="support")
    token = Column(String(128), nullable=False, unique=True, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, accepted, revoked
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    invited_by = relationship("User", foreign_keys=[invited_by_user_id])

    @property
    def is_valid(self):
        return (
            self.status == "pending"
            and self.accepted_at is None
            and self.expires_at > datetime.utcnow()
        )


class TenantInvite(db.Model):
    __tablename__ = "tenant_invites"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(120), nullable=False, index=True)
    token = Column(String(128), nullable=False, unique=True, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role = Column(String(32), nullable=True, default="learner")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    tenant = relationship("Tenant", back_populates="invites")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
    used_by = relationship("User", foreign_keys=[used_by_user_id])

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > datetime.utcnow()


class BillingEvent(db.Model):
    """Idempotent record of subscription payments and plan changes."""
    __tablename__ = "billing_events"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(180), nullable=False, unique=True, index=True)
    source = Column(String(40), nullable=False)  # stripe_webhook, manual_upgrade, checkout_pending
    status = Column(String(30), nullable=False, default="applied")  # applied, duplicate, skipped, pending
    plan_id = Column(String(50), nullable=False)
    billing_cycle = Column(String(20), nullable=False, default="monthly")
    amount_cents = Column(Integer, nullable=True)
    stripe_event_id = Column(String(120), nullable=True, unique=True, index=True)
    stripe_session_id = Column(String(120), nullable=True, unique=True, index=True)
    stripe_subscription_id = Column(String(120), nullable=True)
    billing_period_start = Column(DateTime, nullable=True)
    billing_period_end = Column(DateTime, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", backref=db.backref("billing_events", lazy="dynamic"))


# -------------------------------------
# PasswordResetRequest Model
# -------------------------------------
class PasswordResetRequest(db.Model):
    __tablename__ = 'password_reset_request'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False
    )
    token = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    timestamp = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    # back-reference to User
    user = db.relationship(
        'User',
        back_populates='password_reset_requests',
        passive_deletes=True
    )

# -------------------------------------
# SupportTicket Model
# -------------------------------------
class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False
    )
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)

    # ──────────────── New Column ─────────────────
    # Stores the administrator’s response text
    admin_response = db.Column(db.Text, nullable=True)
    # ───────────────────────────────────────────────

    status = db.Column(db.String(50), default="Open")  # Open, In Progress, Resolved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    assigned_to = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=True
    )

    # Relationships
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref="support_tickets",
        passive_deletes=True
    )
    assignee = db.relationship(
        "User",
        foreign_keys=[assigned_to],
        lazy='joined'
    )
    attachments = db.relationship(
        "SupportAttachment",
        back_populates="ticket",
        cascade="all, delete-orphan"
    )

    def time_taken_minutes(self):
        if self.resolved_at:
            delta = self.resolved_at - self.created_at
            return int(delta.total_seconds() // 60)
        return None

    def __repr__(self):
        return f"<SupportTicket(id={self.id}, user_id={self.user_id}, status={self.status})>"


# -------------------------------------
# SupportAttachment Model
# -------------------------------------
class SupportAttachment(db.Model):
    __tablename__ = 'support_attachments'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    ticket_id = db.Column(
        db.Integer,
        db.ForeignKey('support_tickets.id', ondelete='CASCADE'),
        nullable=False
    )

    # Relationship
    ticket = db.relationship("SupportTicket", back_populates="attachments")

    def __repr__(self):
        return f"<SupportAttachment(id={self.id}, filename='{self.filename}', ticket_id={self.ticket_id})>"
    
# -------------------------------------
# AuditLog Model
# -------------------------------------
class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    # Primary Key
    id = db.Column(Integer, primary_key=True)

    # Event type (e.g. 'USER_LOGIN', 'FAILED_LOGIN', 'STUDY_UPLOAD')
    event_type = db.Column(String(100), nullable=False, index=True)

    # Who did it (nullable for anonymous actions)
    actor_user_id = db.Column(
        Integer,
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    actor_user = relationship(
        'User',
        back_populates='audit_logs',
        passive_deletes=True
    )

    # IP address (IPv4 or IPv6)
    ip_address = db.Column(String(45), nullable=True, index=True)

    # Reference to another record
    target_table = db.Column(String(100), nullable=True, index=True)
    target_id    = db.Column(Integer,        nullable=True, index=True)

    # Arbitrary metadata—store anything as JSONB
    description  = db.Column(JSONB, nullable=True)

    # Timestamp of when it occurred
    created_at   = db.Column(
        TIMESTAMP(timezone=True),
        server_default=db.func.now(),
        nullable=False,
        index=True
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        Index('ix_audit_event_user', 'event_type', 'actor_user_id'),
        Index('ix_audit_target', 'target_table', 'target_id'),
    )


# -------------------------------------
# In-app Notification Model
# -------------------------------------
class Notification(db.Model):
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    category = Column(String(30), nullable=False, default='info')
    icon = Column(String(40), nullable=True)
    link_url = Column(String(500), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    dedupe_key = Column(String(120), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = relationship('User', backref=db.backref('notifications', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body or '',
            'category': self.category,
            'icon': self.icon or 'bell',
            'link_url': self.link_url,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'time_ago': _notification_time_ago(self.created_at),
        }


def _notification_time_ago(dt):
    if not dt:
        return ''
    delta = datetime.utcnow() - (dt.replace(tzinfo=None) if getattr(dt, 'tzinfo', None) else dt)
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return 'Just now'
    if mins < 60:
        return f'{mins}m ago'
    hrs = mins // 60
    if hrs < 24:
        return f'{hrs}h ago'
    days = hrs // 24
    return f'{days}d ago'


# -------------------------------------
# User Agreement Acceptance Audit
# -------------------------------------
class UserAgreementAcceptance(db.Model):
    """Immutable audit trail of platform User Agreement acceptances."""
    __tablename__ = 'user_agreement_acceptances'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    agreement_version = Column(String(20), nullable=False, index=True)
    document_hash = Column(String(64), nullable=False)
    accepted_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    user = relationship('User', backref=db.backref('agreement_acceptances', lazy='dynamic'))


# -------------------------------------
# Organization Announcement Model
# -------------------------------------
class Announcement(db.Model):
    __tablename__ = 'announcements'

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    is_pinned = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    published_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tenant = relationship('Tenant', backref=db.backref('announcements', lazy='dynamic'))
    author = relationship('User', foreign_keys=[created_by_user_id])

    def is_visible(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def dashboard_dict(self) -> dict:
        dt = self.published_at or self.created_at
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            'date': dt.strftime('%b %d, %Y') if dt else '',
            'is_pinned': self.is_pinned,
        }


# -------------------------------------
# Database performance monitoring
# -------------------------------------
class DbPerformanceSnapshot(db.Model):
    """Point-in-time database health metrics collected by the background monitor."""
    __tablename__ = 'db_performance_snapshots'

    id = Column(Integer, primary_key=True)
    collected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    status = Column(String(20), nullable=False, default='healthy', index=True)
    issue_count = Column(Integer, nullable=False, default=0)
    recommendation_count = Column(Integer, nullable=False, default=0)
    summary_json = Column(Text, nullable=True)
    postgres_stats_json = Column(Text, nullable=True)
    mongo_stats_json = Column(Text, nullable=True)

    recommendations = relationship(
        'DbOptimizationRecommendation',
        backref='snapshot',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )
    metric_samples = relationship(
        'DbMetricSample',
        backref='snapshot',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )


class DbMetricSample(db.Model):
    """Time-series samples extracted from monitor snapshots."""
    __tablename__ = 'db_metric_samples'

    id = Column(Integer, primary_key=True)
    collected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    snapshot_id = Column(
        Integer,
        ForeignKey('db_performance_snapshots.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    metric_key = Column(String(80), nullable=False, index=True)
    value = Column(Float, nullable=False)


class DbOptimizationRecommendation(db.Model):
    """Suggested or applied database optimization from the monitor agent."""
    __tablename__ = 'db_optimization_recommendations'

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(
        Integer,
        ForeignKey('db_performance_snapshots.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    action_type = Column(String(40), nullable=False)
    target_key = Column(String(120), nullable=False)
    tier = Column(String(20), nullable=False, default='manual')
    reason = Column(Text, nullable=False)
    ddl = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default='pending', index=True)
    applied_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('snapshot_id', 'target_key', name='uq_db_opt_rec_snapshot_target'),
    )


class DbMaintenanceRun(db.Model):
    """Audit log of CEO-triggered full database maintenance runs."""
    __tablename__ = 'db_maintenance_runs'

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default='running', index=True)
    actor_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    restart_requested = Column(Boolean, nullable=False, default=False)
    restart_status = Column(String(20), nullable=True)
    steps_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    actor = relationship('User', foreign_keys=[actor_user_id])


class PlatformOpsRun(db.Model):
    """Audit log for scheduled and manual platform health cycles."""
    __tablename__ = 'platform_ops_runs'

    id = Column(Integer, primary_key=True)
    source = Column(String(40), nullable=False, index=True)
    trigger = Column(String(20), nullable=False, default='scheduled')
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default='running', index=True)
    actor_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    snapshot_id = Column(Integer, ForeignKey('db_performance_snapshots.id', ondelete='SET NULL'), nullable=True)
    issue_count = Column(Integer, nullable=True)
    indexes_applied = Column(Integer, nullable=False, default=0)
    indexes_failed = Column(Integer, nullable=False, default=0)
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    actor = relationship('User', foreign_keys=[actor_user_id])