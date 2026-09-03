"""Shared FastAPI dependencies.

``get_database`` hands routers the one shared Motor database handle (opened once on
startup in ``mongodb.connect``). Using a dependency — rather than importing the
handle directly — keeps routers decoupled and lets tests override it if needed.
"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from .mongodb import get_db


def get_database() -> AsyncIOMotorDatabase:
    return get_db()
