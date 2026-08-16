from app import app


def test_hello():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "Hello from ChatGPT! 🚀"


def test_counter_increments():
    client = app.test_client()
    first = client.get("/count").get_json()["count"]
    second = client.get("/count").get_json()["count"]
    assert second == first + 1
