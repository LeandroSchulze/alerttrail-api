rom fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session
from ..deps import get_current_user, get_db
from ..auth import get_password_hash
from ..models import User, PlanEnum

router = APIRouter(prefix="/profile", tags=["profile"])

@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "name": user.name, "plan": user.plan.value}

@router.post("/password")
def change_password(new_password: str = Form(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    user.hashed_password = get_password_hash(new_password)
    db.add(user); db.commit()
    return {"ok": True}

@router.post("/plan")
def set_plan(plan: PlanEnum, db: Session = Depends(get_db), user=Depends(get_current_user)):
    user.plan = plan
    db.add(user); db.commit()
    return {"plan": user.plan.value}
2) app/main.py (asegurá la inclusión)
Verificá que tengas esto:

python
Copiar
Editar
from .routers import auth, dashboard, analysis, profile, settings, admin
...
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(analysis.router)
app.include_router(profile.router)     # <- importante
app.include_router(settings.router)
app.include_router(admin.router)