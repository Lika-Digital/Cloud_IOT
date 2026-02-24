"""Customer ↔ Operator chat endpoints."""
import asyncio
import collections
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer, ChatMessage
from ..auth.customer_dependencies import require_customer
from ..auth.dependencies import require_admin
from ..auth.models import User
from ..services.websocket_manager import ws_manager
from ..schemas.customer import ChatMessageResponse, SendMessageRequest, OperatorReplyRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Rate limit: max 10 send calls per 60s per customer_id — protected by a per-customer lock
_RATE_WINDOW = 60
_RATE_MAX = 10
_send_log: dict[int, collections.deque] = {}
_send_lock: dict[int, asyncio.Lock] = {}


@router.post("/send", response_model=ChatMessageResponse)
async def send_message(
    body: SendMessageRequest,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    # Rate limit: 10 messages per 60s per customer (atomic via per-customer Lock)
    if customer.id not in _send_lock:
        _send_lock[customer.id] = asyncio.Lock()
    async with _send_lock[customer.id]:
        now = time.monotonic()
        log = _send_log.setdefault(customer.id, collections.deque())
        while log and now - log[0] > _RATE_WINDOW:
            log.popleft()
        if len(log) >= _RATE_MAX:
            raise HTTPException(status_code=429, detail="Too many messages. Please wait before sending again.")
        log.append(now)

    msg = ChatMessage(
        customer_id=customer.id,
        message=body.message,
        direction="from_customer",
        created_at=datetime.utcnow(),
    )
    user_db.add(msg)
    user_db.commit()
    user_db.refresh(msg)

    await ws_manager.broadcast({
        "event": "chat_message",
        "data": {
            "customer_id": customer.id,
            "message": body.message,
            "direction": "from_customer",
            "created_at": msg.created_at.isoformat(),
        },
    })
    return msg


@router.post("/operator/reply/{customer_id}", response_model=ChatMessageResponse)
async def operator_reply(
    customer_id: int,
    body: OperatorReplyRequest,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    customer = user_db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    msg = ChatMessage(
        customer_id=customer_id,
        message=body.message,
        direction="from_operator",
        created_at=datetime.utcnow(),
    )
    user_db.add(msg)
    user_db.commit()
    user_db.refresh(msg)

    await ws_manager.broadcast({
        "event": "chat_message",
        "data": {
            "customer_id": customer_id,
            "message": body.message,
            "direction": "from_operator",
            "created_at": msg.created_at.isoformat(),
        },
    })
    return msg


@router.get("/messages/{customer_id}", response_model=list[ChatMessageResponse])
def get_messages(
    customer_id: int,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    return (
        user_db.query(ChatMessage)
        .filter(ChatMessage.customer_id == customer_id)
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )


@router.post("/mark-read/{customer_id}")
def mark_read(
    customer_id: int,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    now = datetime.utcnow()
    msgs = (
        user_db.query(ChatMessage)
        .filter(
            ChatMessage.customer_id == customer_id,
            ChatMessage.direction == "from_customer",
            ChatMessage.read_at.is_(None),
        )
        .all()
    )
    for m in msgs:
        m.read_at = now
    user_db.commit()
    return {"marked": len(msgs)}


@router.get("/unread-count")
def unread_count(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    from sqlalchemy import func, distinct
    count = (
        user_db.query(func.count(distinct(ChatMessage.customer_id)))
        .filter(ChatMessage.direction == "from_customer", ChatMessage.read_at.is_(None))
        .scalar()
    )
    return {"unread_customers": count or 0}


@router.get("/my-messages", response_model=list[ChatMessageResponse])
def my_messages(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    return (
        user_db.query(ChatMessage)
        .filter(ChatMessage.customer_id == customer.id)
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )
