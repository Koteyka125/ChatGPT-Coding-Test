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


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)


def init_db():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "user_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN user_id INTEGER"))


init_db()


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


def user_task(db: Session, task_id: int):
    return db.scalar(select(Task).where(Task.id == task_id, Task.user_id == current_user_id()))


@app.get("/")
@login_required
def index():
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "all").strip().lower()
    if status not in {"all", "active", "done"}:
        status = "all"

    with Session(engine) as db:
        query = select(Task).where(Task.user_id == current_user_id())
        if search:
            query = query.where(Task.title.ilike(f"%{search}%"))
        if status == "active":
            query = query.where(Task.done.is_(False))
        elif status == "done":
            query = query.where(Task.done.is_(True))
        tasks = db.scalars(query.order_by(Task.id.desc())).all()

    return render_template(
        "index.html",
        tasks=tasks,
        username=session.get("username"),
        search=search,
        status=status,
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
                    user = User(
                        username=username,
                        password_hash=generate_password_hash(password),
                    )
                    db.add(user)
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


@app.post("/tasks")
@login_required
def create_task():
    if not validate_csrf():
        return "Invalid CSRF token", 400
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("index"))
    with Session(engine) as db:
        db.add(Task(title=title, user_id=current_user_id()))
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
        task = user_task(db, task_id)
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
        task = user_task(db, task_id)
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
        task = user_task(db, task_id)
        if task is not None:
            db.delete(task)
            db.commit()
    return redirect(url_for("index"))


@app.get("/count")
@login_required
def counter():
    with Session(engine) as db:
        count = db.scalar(
            select(func.count()).select_from(Task).where(Task.user_id == current_user_id())
        )
    return jsonify(count=count)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(select(1))
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
