from flask import Flask

app = Flask(__name__)
count = 0


@app.get("/")
def hello():
    return "Hello from ChatGPT! 🚀"


@app.get("/count")
def counter():
    global count
    count += 1
    return {"count": count}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
