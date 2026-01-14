# app/services/seat_limits.py

from app.config.plans import PLANS


def max_seats_for_plan(plan: str) -> int:
    plan = (plan or "FREE").upper()
    return PLANS.get(plan, PLANS["FREE"])["seats"]
