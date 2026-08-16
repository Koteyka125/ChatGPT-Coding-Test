import os
from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy import Boolean, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

app = Flask(__name__)

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


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


def init_db():
    Base.metadata.create_all(engine)


init_db()


@app.get("/")
def index():
    with Session(engine) as db:
        tasks = db.scalars(select(Task).order_by(Task.id.desc())).all()
    return render_template("index.html", tasks=tasks)


@app.post("/tasks")
def create_task():
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("index"))
    with Session(engine) as db:
        db.add(Task(title=title))
        db.commit()
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/toggle")
def toggle_task(task_id):
    with Session(engine) as db:
        task = db.get(Task, task_id)
        if task is not None:
            task.done = not task.done
            db.commit()
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/delete")
def delete_task(task_id):
    with Session(engine) as db:
        task = db.get(Task, task_id)
        if task is not None:
            db.delete(task)
            db.commit()
    return redirect(url_for("index"))


@app.get("/count")
def counter():
    with Session(engine) as db:
        count = db.scalar(select(func.count()).select_from(Task))
    return jsonify(count=count)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(select(1))
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
