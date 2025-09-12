from fastapi import FastAPI
from app.routers import auth, analysis, mail

app = FastAPI(title="AlertTrail")

app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(mail.router)

@app.get("/health")
def health():
    return {"status": "ok"}
