import os
import sqlite3
from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)

DATABASE = os.environ.get("DATABASE_PATH", "tasks.db")


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                done INTEGER NOT NULL DEFAULT 0
            )
            """
        )


init_db()


@app.get("/")
def index():
    with get_db() as db:
        tasks = db.execute("SELECT id, title, done FROM tasks ORDER BY id DESC").fetchall()
    return render_template("index.html", tasks=tasks)


@app.post("/tasks")
def create_task():
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("index"))
    with get_db() as db:
        db.execute("INSERT INTO tasks (title) VALUES (?)", (title,))
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/toggle")
def toggle_task(task_id):
    with get_db() as db:
        db.execute(
            "UPDATE tasks SET done = CASE done WHEN 0 THEN 1 ELSE 0 END WHERE id = ?",
            (task_id,),
        )
    return redirect(url_for("index"))


@app.post("/tasks/<int:task_id>/delete")
def delete_task(task_id):
    with get_db() as db:
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return redirect(url_for("index"))


@app.get("/count")
def counter():
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()
    return jsonify(count=row["count"])


@app.get("/health")
def health():
    with get_db() as db:
        db.execute("SELECT 1")
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
