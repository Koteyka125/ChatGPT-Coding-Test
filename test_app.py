import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"

    import app as app_module

    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(app_module, "engine", test_engine)
    app_module.Base.metadata.create_all(test_engine)
    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret")

    with app_module.app.test_client() as client:
        yield client

    test_engine.dispose()


def csrf_token(client):
    client.get("/login")
    with client.session_transaction() as flask_session:
        return flask_session["csrf_token"]


def post_with_csrf(client, url, data=None, **kwargs):
    payload = dict(data or {})
    payload["csrf_token"] = csrf_token(client)
    return client.post(url, data=payload, **kwargs)


def register_and_login(client, username="alice", password="secret"):
    response = post_with_csrf(
        client,
        "/register",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return post_with_csrf(
        client,
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def logout(client):
    post_with_csrf(client, "/logout")


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_register_and_login(client):
    response = register_and_login(client)
    assert response.status_code == 200
    assert "alice" in response.text


def test_duplicate_username_is_rejected(client):
    register_and_login(client)
    logout(client)
    response = post_with_csrf(client, "/register", data={"username": "alice", "password": "other"})
    assert response.status_code == 200
    assert "уже существует" in response.text


def test_wrong_password_is_rejected(client):
    post_with_csrf(client, "/register", data={"username": "alice", "password": "secret"})
    response = post_with_csrf(client, "/login", data={"username": "alice", "password": "wrong"})
    assert response.status_code == 200
    assert "Неверное имя пользователя или пароль" in response.text


def test_tasks_require_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_create_task(client):
    register_and_login(client)
    response = post_with_csrf(client, "/tasks", data={"title": "Купить молоко"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Купить молоко" in response.text


def test_empty_task_is_ignored(client):
    register_and_login(client)
    response = post_with_csrf(client, "/tasks", data={"title": "   "}, follow_redirects=True)
    assert response.status_code == 200
    assert '<span class="title">' not in response.text


def test_toggle_task(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Тест"})
    post_with_csrf(client, "/tasks/1/toggle")
    response = client.get("/")
    assert '<li class="done">' in response.text


def test_edit_task(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Старое название"})
    response = post_with_csrf(
        client,
        "/tasks/1/edit",
        data={"title": "Новое название"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Новое название" in response.text
    assert "Старое название" not in response.text


def test_empty_edit_is_ignored(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Оригинал"})
    response = post_with_csrf(
        client,
        "/tasks/1/edit",
        data={"title": "   "},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Оригинал" in response.text


def test_edit_cannot_modify_another_users_task(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/tasks", data={"title": "Alice task"})
    logout(client)

    register_and_login(client, "bob")
    post_with_csrf(client, "/tasks/1/edit", data={"title": "Bob renamed"})
    logout(client)

    register_and_login(client, "alice")
    response = client.get("/")
    assert "Alice task" in response.text
    assert "Bob renamed" not in response.text


def test_delete_task(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Удалить"})
    post_with_csrf(client, "/tasks/1/delete")
    response = client.get("/")
    assert '<span class="title">Удалить</span>' not in response.text


def test_count_is_number_of_tasks(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Одна"})
    post_with_csrf(client, "/tasks", data={"title": "Две"})
    assert client.get("/count").get_json() == {"count": 2}


def test_logout(client):
    register_and_login(client)
    logout(client)
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_users_only_see_their_own_tasks(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/tasks", data={"title": "Alice task"})
    logout(client)

    register_and_login(client, "bob")
    post_with_csrf(client, "/tasks", data={"title": "Bob task"})
    response = client.get("/")

    assert "Bob task" in response.text
    assert "Alice task" not in response.text
    assert client.get("/count").get_json() == {"count": 1}


def test_user_cannot_modify_another_users_task(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/tasks", data={"title": "Alice task"})
    logout(client)

    register_and_login(client, "bob")
    post_with_csrf(client, "/tasks/1/toggle")
    post_with_csrf(client, "/tasks/1/delete")

    logout(client)
    register_and_login(client, "alice")
    response = client.get("/")
    assert "Alice task" in response.text


def test_task_is_saved_with_current_user(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/tasks", data={"title": "Alice task"})

    import app as app_module
    with Session(app_module.engine) as db:
        task = db.scalar(select(app_module.Task).where(app_module.Task.title == "Alice task"))
        user = db.scalar(select(app_module.User).where(app_module.User.username == "alice"))
        assert task.user_id == user.id


def test_post_without_csrf_is_rejected(client):
    response = client.post("/register", data={"username": "attacker", "password": "secret"})
    assert response.status_code == 400


def test_session_cookie_security_flags(client):
    register_and_login(client)
    cookie = client.get_cookie("session")
    assert cookie is not None
    assert cookie.http_only is True
    assert cookie.same_site == "Lax"


def test_task_idor_cannot_read_or_change_foreign_task(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/tasks", data={"title": "Alice task"})
    logout(client)

    register_and_login(client, "bob")
    response = client.post("/tasks/1/toggle", data={"csrf_token": csrf_token(client)})
    assert response.status_code == 302
    logout(client)

    register_and_login(client, "alice")
    response = client.get("/")
    assert "Alice task" in response.text
    assert '<li class="done">' not in response.text
