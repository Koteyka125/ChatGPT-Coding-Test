import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    import app as app_module
    app_module.DATABASE = str(db_path)
    app_module.init_db()
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        yield client


def test_hello(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Мои задачи" in response.text


def test_create_task(client):
    response = client.post("/tasks", data={"title": "Купить молоко"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Купить молоко" in response.text


def test_empty_task_is_ignored(client):
    response = client.post("/tasks", data={"title": "   "}, follow_redirects=True)
    assert response.status_code == 200
    assert '<span class="title">' not in response.text


def test_toggle_task(client):
    client.post("/tasks", data={"title": "Тест"})
    client.post("/tasks/1/toggle")
    response = client.get("/")
    assert "done" in response.text


def test_delete_task(client):
    client.post("/tasks", data={"title": "Удалить"})
    client.post("/tasks/1/delete")
    response = client.get("/")
    assert '<span class="title">Удалить</span>' not in response.text


def test_count_is_number_of_tasks(client):
    client.post("/tasks", data={"title": "Одна"})
    client.post("/tasks", data={"title": "Две"})
    assert client.get("/count").get_json() == {"count": 2}


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}
