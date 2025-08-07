from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from app.routes import auth_routes, analysis_routes, history_routes, user_routes
import os

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def home():
    return templates.TemplateResponse("login.html", {"request": {}})


# Incluir rutas de la app
app.include_router(auth_routes.router)
app.include_router(analysis_routes.router)
app.include_router(history_routes.router)
app.include_router(user_routes.router)
