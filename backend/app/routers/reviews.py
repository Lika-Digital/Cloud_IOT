"""Customer service reviews — 1-5 stars with optional comment."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer
from ..auth.contract_models import ServiceReview
from ..auth.customer_dependencies import require_customer
from ..auth.dependencies import require_admin
from ..auth.models import User

router = APIRouter(tags=["reviews"])


class ReviewSubmit(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    session_id: Optional[int] = None
    service_order_id: Optional[int] = None


class ReviewResponse(BaseModel):
    id: int
    customer_id: int
    stars: int
    comment: Optional[str]
    session_id: Optional[int]
    service_order_id: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminReviewResponse(ReviewResponse):
    customer_name: Optional[str]
    customer_email: str


@router.post("/api/customer/reviews/", response_model=ReviewResponse)
def submit_review(
    body: ReviewSubmit,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    review = ServiceReview(
        customer_id=customer.id,
        stars=body.stars,
        comment=body.comment,
        session_id=body.session_id,
        service_order_id=body.service_order_id,
    )
    user_db.add(review)
    user_db.commit()
    user_db.refresh(review)
    return review


@router.get("/api/customer/reviews/mine", response_model=list[ReviewResponse])
def get_my_reviews(
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    return (
        user_db.query(ServiceReview)
        .filter(ServiceReview.customer_id == customer.id)
        .order_by(ServiceReview.created_at.desc())
        .all()
    )


@router.get("/api/admin/reviews/", response_model=list[AdminReviewResponse])
def get_all_reviews(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    rows = (
        user_db.query(ServiceReview, Customer)
        .join(Customer, Customer.id == ServiceReview.customer_id)
        .order_by(ServiceReview.created_at.desc())
        .all()
    )
    result = []
    for review, cust in rows:
        result.append(AdminReviewResponse(
            id=review.id,
            customer_id=review.customer_id,
            stars=review.stars,
            comment=review.comment,
            session_id=review.session_id,
            service_order_id=review.service_order_id,
            created_at=review.created_at,
            customer_name=cust.name,
            customer_email=cust.email,
        ))
    return result
