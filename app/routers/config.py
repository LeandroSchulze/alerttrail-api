# app/routers/config.py
import os
from fastapi import APIRouter

router = APIRouter()

@router.get("/public-config")
def public_config():
    return {
        "vapidPublicKey": os.getenv("VAPID_PUBLIC_KEY", "")
    }
