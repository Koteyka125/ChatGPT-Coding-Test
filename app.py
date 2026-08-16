import os
import secrets
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import Boolean, ForeignKey, Integer, String, create_engine, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "test-secret-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{os.environ.get('DATABASE_PATH', 'tasks.db')}"
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")


class ProjectInvitation(Base):
    __tablename__ = "project_invitations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    inviter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    invitee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)


def init_db():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    with engine.begin() as connection:
        if "user_id" not in task_columns:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN user_id INTEGER"))
        if "project_id" not in task_columns:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN project_id INTEGER"))

    with Session(engine) as db:
        users = db.scalars(select(User)).all()
        for user in users:
            ensure_personal_project(db, user.id)
        db.commit()


@app.before_request
def ensure_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


def validate_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("csrf_token")
    return bool(expected and token and secrets.compare_digest(token, expected))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def current_user_id():
    return int(session["user_id"])


def ensure_personal_project(db: Session, user_id: int):
    personal = db.scalar(
        select(Project)
        .where(Project.owner_id == user_id, Project.name == "Личное")
        .order_by(Project.id)
    )
    if personal is None:
        personal = Project(name="Личное", owner_id=user_id)
        db.add(personal)
        db.flush()
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == personal.id,
            ProjectMember.user_id == user_id,
        )
    )
    if membership is None:
        db.add(ProjectMember(project_id=personal.id, user_id=user_id, role="owner"))
    db.execute(
        text(
            "UPDATE tasks SET project_id = :project_id "
            "WHERE user_id = :user_id AND project_id IS NULL"
        ),
        {"project_id": personal.id, "user_id": user_id},
    )
    return personal


def current_membership(db: Session, project_id: int | None):
    if project_id is None:
        return None
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user_id(),
        )
    )


def ensure_selected_project(db: Session):
    selected = session.get("project_id")
    if selected is not None and current_membership(db, int(selected)) is not None:
        return int(selected)
    project_id = db.scalar(
        select(ProjectMember.project_id)
        .where(ProjectMember.user_id == current_user_id())
        .order_by(ProjectMember.project_id)
    )
    if project_id is None:
        personal = ensure_personal_project(db, current_user_id())
        db.commit()
        project_id = personal.id
    session["project_id"] = int(project_id)
    return int(project_id)


def accessible_projects(db: Session):
    return db.scalars(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == current_user_id())
        .order_by(Project.id)
    ).all()


def task_in_current_project(db: Session, task_id: int):
    project_id = ensure_selected_project(db)
    if current_membership(db, project_id) is None:
        return None
    return db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))


@app.get("/")
@login_required
def index():
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "all").strip().lower()
    if status not in {"all", "active", "done"}:
        status = "all"

    with Session(engine) as db:
        project_id = ensure_selected_project(db)
        projects = accessible_projects(db)
        selected_project = db.get(Project, project_id) if project_id else None
        query = select(Task).where(Task.project_id == project_id)
        if search:
            query = query.where(Task.title.ilike(f"%{search}%"))
        if status == "active":
            query = query.where(Task.done.is_(False))
        elif status == "done":
            query = query.where(Task.done.is_(True))
        tasks = db.scalars(query.order_by(Task.id.desc())).all()
        pending_invites = db.scalar(
            select(func.count())
            .select_from(ProjectInvitation)
            .where(
                ProjectInvitation.invitee_id == current_user_id(),
                ProjectInvitation.status == "pending",
            )
        ) or 0
    return render_template(
        "index.html",
        tasks=tasks,
        username=session.get("username"),
        search=search,
        status=status,
        projects=projects,
        selected_project=selected_project,
        pending_invites=pending_invites,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        if not validate_csrf():
            return "Invalid CSRF token", 400
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "Введите имя пользователя и пароль."
        elif len(username) > 80:
            error = "Имя пользователя слишком длинное."
        else:
            with Session(engine) as db:
                existing = db.scalar(select(User).where(User.username == username))
                if existing is not None:
                    error = "Такой пользователь уже существует."
                else:
                    user = User(username=username, password_hash=generate_password_hash(password))
                    db.add(user)
                    db.flush()
                    ensure_personal_project(db, user.id)
                    db.commit()
                    return redirect(url_for("login"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if not validate_csrf():
            return "Invalid CSRF token", 400
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.username == username))
        if user is None or not check_password_hash(user.password_hash, password):
            error = "Неверное имя пользователя или пароль."
        else:
            csrf_token = session.get("csrf_token")
            session.clear()
            session["csrf_token"] = csrf_token or secrets.token_urlsafe(32)
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect(url_for("index"))
    return render_template("login.html", error=error)


@app.post("/logout")
def logout():
    if not validate_csrf():
        return "Invalid CSRF token", 400
    session.clear()
    return redirect(url_for("login"))


@app.post("/projects")
@login_required
def create_project():
    if not validate_csrf():
        return "Invalid CSRF token", 400
    name = request.form.get("name", "").strip()
    if not name or len(name) > 120:
        return redirect(url_for("index"))
    with Session(engine) as db:
        project = Project(name=name, owner_id=current_user_id())
        db.add(project)
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=current_user_id(), role="owner"))
        db.commit()
        session["project_id"] = project.id
    return redirect(url_for("index"))


@app.post("/projects/<int:project_id>/select")
@login_required
def select_project(project_id):
    if not validate_csrf():
        return "Invalid CSRF token", 400
    with Session(engine) as db:
        if current_membership(db, project_id) is not None:
            session["project_id"] = project_id
    return redirect(url_for("index"))


@app.post("/projects/<int:project_id>/invite")
@login_required
def invite_to_project(project_id):
    if not validate_csrf():
        return "Invalid CSRF token", 400
    username = request.form.get("username", "").strip()
    with Session(engine) as db:
        membership = current_membership(db, project_id)
        if membership is None or membership.role != "owner":
            return "Forbidden", 403
        invitee = db.scalar(select(User).where(User.username == username))
        if invitee is None or invitee.id == current_user_id():
            return redirect(url_for("index"))
        existing_member = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == invitee.id,
            )
        )
        if existing_member is not None:
            return redirect(url_for("index"))
        pending = db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.invitee_id == invitee.id,
                ProjectInvitation.status == "pending",
            )
        )
        if pending is None:
            db.add(
                ProjectInvitation(
                    project_id=project_id,
                    inviter_id=current_user_id(),
                    invitee_id=invitee.id,
                    token=secrets.token_urlsafe(32),
                )
            )
            db.commit()
    return redirect(url_for("index"))


@app.get("/invitations")
@login_required
def invitations():
    with Session(engine) as db:
        invites = db.scalars(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.invitee_id == current_user_id(),
                ProjectInvitation.status == "pending",
            )
            .order_by(ProjectInvitation.id.desc())
        ).all()
        projects = {invite.project_id: db.get(Project, invite.project_id) for invite in invites}
    return render_template("invitations.html", invitations=invites, projects=projects)


@app.post("/invitations/<token>/accept")
@login_required
def accept_invitation(token):
    if not validate_csrf():
        return "Invalid CSRF token", 400
    with Session(engine) as db:
        invite = db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.token == token,
                ProjectInvitation.invitee_id == current_user_id(),
                ProjectInvitation.status == "pending",
            )
        )
        if invite is not None:
            existing = db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == invite.project_id,
                    ProjectMember.user_id == current_user_id(),
                )
            )
            if existing is None:
                db.add(ProjectMember(project_id=invite.project_id, user_id=current_user_id(), role="member"))
            invite.status = "accepted"
            db.commit()
            session["project_id"] = invite.project_id
    return redirect(url_for("index"))


@app.post("/tasks")
@login_required
def create_task():
    if not validate_csrf():
        return "Invalid CSRF token", 400
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("index"))
    with Session(engine) as db:
        project_id = ensure_selected_project(db)
        db.add(Task(title=title, user_id=current_user_id(), project_id=project_id))
        db.commit()
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/edit")
@login_required
def edit_task(task_id):
    if not validate_csrf():
        return "Invalid CSRF token", 400
    title = request.form.get("title", "").strip()
    if not title or len(title) > 500:
        return redirect(url_for("index"))
    with Session(engine) as db:
        task = task_in_current_project(db, task_id)
        if task is not None:
            task.title = title
            db.commit()
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/toggle")
@login_required
def toggle_task(task_id):
    if not validate_csrf():
        return "Invalid CSRF token", 400
    with Session(engine) as db:
        task = task_in_current_project(db, task_id)
        if task is not None:
            task.done = not task.done
            db.commit()
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/delete")
@login_required
def delete_task(task_id):
    if not validate_csrf():
        return "Invalid CSRF token", 400
    with Session(engine) as db:
        task = task_in_current_project(db, task_id)
        if task is not None:
            db.delete(task)
            db.commit()
    return redirect(url_for("index"))


@app.get("/count")
@login_required
def counter():
    with Session(engine) as db:
        project_id = ensure_selected_project(db)
        count = db.scalar(select(func.count()).select_from(Task).where(Task.project_id == project_id))
    return jsonify(count=count)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(select(1))
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

init_db()
