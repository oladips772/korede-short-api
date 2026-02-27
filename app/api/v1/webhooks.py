from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def list_webhooks():
    """Placeholder for webhook management."""
    return {"webhooks": []}
