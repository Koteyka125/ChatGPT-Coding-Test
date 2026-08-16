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
    response = post_with_csrf(client, "/register", data={"username": username, "password": password}, follow_redirects=True)
    assert response.status_code == 200
    return post_with_csrf(client, "/login", data={"username": username, "password": password}, follow_redirects=True)


def logout(client):
    post_with_csrf(client, "/logout")


def project_id_for(client, name):
    import app as app_module
    with Session(app_module.engine) as db:
        return db.scalar(select(app_module.Project.id).where(app_module.Project.name == name))


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_register_and_login(client):
    response = register_and_login(client)
    assert response.status_code == 200
    assert "alice" in response.text
    assert "Личное" in response.text


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
    response = post_with_csrf(client, "/tasks/1/edit", data={"title": "Новое название"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Новое название" in response.text
    assert "Старое название" not in response.text


def test_empty_edit_is_ignored(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Оригинал"})
    response = post_with_csrf(client, "/tasks/1/edit", data={"title": "   "}, follow_redirects=True)
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
        assert task.project_id is not None


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


def test_search_filters_tasks_but_respects_user_ownership(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/tasks", data={"title": "Buy milk"})
    post_with_csrf(client, "/tasks", data={"title": "Write report"})
    logout(client)
    register_and_login(client, "bob")
    post_with_csrf(client, "/tasks", data={"title": "Milk for Bob"})
    response = client.get("/?q=milk")
    assert "Milk for Bob" in response.text
    assert "Buy milk" not in response.text
    assert "Write report" not in response.text


def test_status_filter_returns_only_requested_tasks(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "Active task"})
    post_with_csrf(client, "/tasks", data={"title": "Done task"})
    post_with_csrf(client, "/tasks/2/toggle")
    active = client.get("/?status=active")
    assert "Active task" in active.text
    assert "Done task" not in active.text
    done = client.get("/?status=done")
    assert "Done task" in done.text
    assert "Active task" not in done.text


def test_invalid_status_defaults_to_all(client):
    register_and_login(client)
    post_with_csrf(client, "/tasks", data={"title": "One"})
    response = client.get("/?status=unknown")
    assert "One" in response.text


def test_create_project_and_switch(client):
    register_and_login(client)
    response = post_with_csrf(client, "/projects", data={"name": "Work"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Work" in response.text
    post_with_csrf(client, "/tasks", data={"title": "Work task"})
    post_with_csrf(client, "/projects/1/select")
    response = client.get("/")
    assert "Work task" in response.text


def test_personal_project_is_created_for_new_users(client):
    register_and_login(client, "alice")
    assert "Личное" in client.get("/").text
    import app as app_module
    with Session(app_module.engine) as db:
        user = db.scalar(select(app_module.User).where(app_module.User.username == "alice"))
        membership = db.scalar(select(app_module.ProjectMember).where(app_module.ProjectMember.user_id == user.id))
        assert membership.role == "owner"


def test_owner_can_invite_existing_user(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/projects", data={"name": "Team"})
    logout(client)
    register_and_login(client, "bob")
    logout(client)
    register_and_login(client, "alice")
    project_id = project_id_for(client, "Team")
    response = post_with_csrf(client, f"/projects/{project_id}/invite", data={"username": "bob"})
    assert response.status_code == 302
    import app as app_module
    with Session(app_module.engine) as db:
        invite = db.scalar(select(app_module.ProjectInvitation).where(app_module.ProjectInvitation.project_id == project_id))
        assert invite is not None
        assert invite.status == "pending"
        assert invite.invitee_id != invite.inviter_id


def test_only_project_owner_can_invite(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/projects", data={"name": "Team"})
    project_id = project_id_for(client, "Team")
    logout(client)
    register_and_login(client, "bob")
    response = post_with_csrf(client, f"/projects/{project_id}/invite", data={"username": "alice"})
    assert response.status_code == 403


def test_invitee_can_accept_and_join_project(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/projects", data={"name": "Team"})
    project_id = project_id_for(client, "Team")
    logout(client)
    register_and_login(client, "bob")
    logout(client)
    register_and_login(client, "alice")
    post_with_csrf(client, f"/projects/{project_id}/invite", data={"username": "bob"})
    import app as app_module
    with Session(app_module.engine) as db:
        invite = db.scalar(select(app_module.ProjectInvitation).where(app_module.ProjectInvitation.project_id == project_id))
        token = invite.token
    logout(client)
    register_and_login(client, "bob")
    response = client.get("/invitations")
    assert "Team" in response.text
    response = post_with_csrf(client, f"/invitations/{token}/accept", follow_redirects=True)
    assert response.status_code == 200
    assert "Team" in response.text
    with Session(app_module.engine) as db:
        membership = db.scalar(select(app_module.ProjectMember).where(app_module.ProjectMember.project_id == project_id, app_module.ProjectMember.user_id == db.scalar(select(app_module.User.id).where(app_module.User.username == "bob"))))
        invite = db.scalar(select(app_module.ProjectInvitation).where(app_module.ProjectInvitation.token == token))
        assert membership.role == "member"
        assert invite.status == "accepted"


def test_non_member_cannot_select_or_see_project_tasks(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/projects", data={"name": "Private"})
    project_id = project_id_for(client, "Private")
    post_with_csrf(client, "/tasks", data={"title": "Secret task"})
    logout(client)
    register_and_login(client, "bob")
    post_with_csrf(client, f"/projects/{project_id}/select")
    response = client.get("/")
    assert "Secret task" not in response.text
    assert "Private" not in response.text


def test_shared_project_tasks_are_visible_to_member(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/projects", data={"name": "Team"})
    project_id = project_id_for(client, "Team")
    logout(client)
    register_and_login(client, "bob")
    logout(client)
    register_and_login(client, "alice")
    post_with_csrf(client, f"/projects/{project_id}/invite", data={"username": "bob"})
    import app as app_module
    with Session(app_module.engine) as db:
        token = db.scalar(select(app_module.ProjectInvitation.token).where(app_module.ProjectInvitation.project_id == project_id))
    logout(client)
    register_and_login(client, "bob")
    post_with_csrf(client, f"/invitations/{token}/accept")
    post_with_csrf(client, "/tasks", data={"title": "Shared task"})
    response = client.get("/")
    assert "Shared task" in response.text
    assert client.get("/count").get_json() == {"count": 1}


def test_member_can_modify_shared_task_but_non_member_cannot(client):
    register_and_login(client, "alice")
    post_with_csrf(client, "/projects", data={"name": "Team"})
    project_id = project_id_for(client, "Team")
    post_with_csrf(client, "/tasks", data={"title": "Shared"})
    logout(client)
    register_and_login(client, "bob")
    logout(client)
    register_and_login(client, "alice")
    post_with_csrf(client, f"/projects/{project_id}/invite", data={"username": "bob"})
    import app as app_module
    with Session(app_module.engine) as db:
        token = db.scalar(select(app_module.ProjectInvitation.token).where(app_module.ProjectInvitation.project_id == project_id))
        task_id = db.scalar(select(app_module.Task.id).where(app_module.Task.title == "Shared"))
    logout(client)
    register_and_login(client, "bob")
    post_with_csrf(client, f"/invitations/{token}/accept")
    post_with_csrf(client, f"/tasks/{task_id}/edit", data={"title": "Shared renamed"})
    assert "Shared renamed" in client.get("/").text
    logout(client)
    register_and_login(client, "charlie")
    post_with_csrf(client, f"/tasks/{task_id}/edit", data={"title": "Hacked"})
    assert "Hacked" not in client.get("/").text


def test_search_and_status_are_scoped_to_selected_project(client):
    register_and_login(client)
    post_with_csrf(client, "/projects", data={"name": "One"})
    one_id = project_id_for(client, "One")
    post_with_csrf(client, "/tasks", data={"title": "Milk in one"})
    post_with_csrf(client, f"/projects/{one_id}/select")
    post_with_csrf(client, "/projects", data={"name": "Two"})
    two_id = project_id_for(client, "Two")
    post_with_csrf(client, "/tasks", data={"title": "Milk in two"})
    post_with_csrf(client, f"/projects/{one_id}/select")
    response = client.get("/?q=milk")
    assert "Milk in one" in response.text
    assert "Milk in two" not in response.text
    response = client.get("/?status=active")
    assert "Milk in one" in response.text
    assert two_id != one_id


def test_legacy_task_without_project_is_migrated_to_personal_project(client):
    register_and_login(client, "alice")
    import app as app_module
    with Session(app_module.engine) as db:
        user = db.scalar(select(app_module.User).where(app_module.User.username == "alice"))
        db.add(app_module.Task(title="Legacy", user_id=user.id, project_id=None))
        db.commit()
    app_module.init_db()
    with Session(app_module.engine) as db:
        task = db.scalar(select(app_module.Task).where(app_module.Task.title == "Legacy"))
        assert task.project_id is not None
        personal = db.scalar(select(app_module.Project).where(app_module.Project.id == task.project_id))
        assert personal.name == "Личное"
