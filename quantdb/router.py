from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.staticfiles import StaticFiles

from quantdb.api_server import app as quantdb_flask_app

app = FastAPI()
app.mount('/quantdb', WSGIMiddleware(quantdb_flask_app))


# Root URL
@app.get('/')
def index() -> Literal['Hello']:
    return 'Hello'


if __name__ == '__main__':
    uvicorn.run('router:app', host='localhost', port=8000, reload=True)
