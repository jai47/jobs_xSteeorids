from fastapi import APIRouter

from db.engine import check_db_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    try:
        check_db_connection()
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        return {"status": "error", "db": str(exc)}
