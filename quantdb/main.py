from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from quantdb.api_server import app as flask_app

app = FastAPI()

app.mount("/", WSGIMiddleware(flask_app))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("quantdb.main:app", host="127.0.0.1", port=8990, reload=True)
