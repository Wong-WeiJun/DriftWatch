from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from app.services import store

router = APIRouter(prefix="/drifts", tags=["drifts"])


@router.get("/events")
def list_events(
    scan_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return store.list_drift_events(scan_id=scan_id, limit=limit)


@router.get("/scans/{scan_id}")
def get_scan_summary(scan_id: str) -> dict[str, Any]:
    summary = store.get_scan_summary(scan_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return summary
