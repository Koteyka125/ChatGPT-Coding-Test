import pytest
from sqlalchemy import create_engine


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


def register_and_login(client, username="alice", password="secret"):
    response = client.post(
        "/register",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_register_and_login(client):
    response = register_and_login(client)
    assert response.status_code == 200
    assert "alice" in response.text


def test_duplicate_username_is_rejected(client):
    register_and_login(client)
    client.post("/logout")
    response = client.post("/register", data={"username": "alice", "password": "other"})
    assert response.status_code == 200
    assert "уже существует" in response.text


def test_wrong_password_is_rejected(client):
    client.post("/register", data={"username": "alice", "password": "secret"})
    response = client.post("/login", data={"username": "alice", "password": "wrong"})
    assert response.status_code == 200
    assert "Неверное имя пользователя или пароль" in response.text


def test_tasks_require_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_create_task(client):
    register_and_login(client)
    response = client.post("/tasks", data={"title": "Купить молоко"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Купить молоко" in response.text


def test_empty_task_is_ignored(client):
    register_and_login(client)
    response = client.post("/tasks", data={"title": "   "}, follow_redirects=True)
    assert response.status_code == 200
    assert '<span class="title">' not in response.text


def test_toggle_task(client):
    register_and_login(client)
    client.post("/tasks", data={"title": "Тест"})
    client.post("/tasks/1/toggle")
    response = client.get("/")
    assert "done" in response.text


def test_delete_task(client):
    register_and_login(client)
    client.post("/tasks", data={"title": "Удалить"})
    client.post("/tasks/1/delete")
    response = client.get("/")
    assert '<span class="title">Удалить</span>' not in response.text


def test_count_is_number_of_tasks(client):
    register_and_login(client)
    client.post("/tasks", data={"title": "Одна"})
    client.post("/tasks", data={"title": "Две"})
    assert client.get("/count").get_json() == {"count": 2}


def test_logout(client):
    register_and_login(client)
    client.post("/logout")
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
