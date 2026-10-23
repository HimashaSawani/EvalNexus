import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.database.models import Customer, Order, RefundRequest


class RefundDomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class RefundService:
    def __init__(self, db: Session, scenario_run_id: str, fixed_clock: datetime.datetime):
        self.db = db
        self.scenario_run_id = scenario_run_id
        self.fixed_clock = fixed_clock

    def get_order(self, session_customer_id: str, order_id: str) -> Dict[str, Any]:
        """
        Tool 1: get_order
        Strictly enforces customer identity from authenticated session.
        Never trust customer_id supplied by agent.
        """
        order = self.db.query(Order).filter(
            Order.id == order_id,
            Order.scenario_run_id == self.scenario_run_id
        ).first()

        if not order:
            raise RefundDomainError(
                code="ORDER_NOT_FOUND",
                message=f"Order '{order_id}' was not found in the system.",
                status_code=404
            )

        # Ownership enforcement
        if order.customer_id != session_customer_id:
            raise RefundDomainError(
                code="UNAUTHORIZED_ORDER_ACCESS",
                message=f"Access denied: Order '{order_id}' does not belong to customer '{session_customer_id}'.",
                status_code=403
            )

        return {
            "order_id": order.id,
            "customer_id": order.customer_id,
            "status": order.status,
            "total_amount_cents": order.total_amount_cents,
            "currency": order.currency,
            "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
            "created_at": order.created_at.isoformat() if order.created_at else None
        }

    def check_refund_eligibility(self, session_customer_id: str, order_id: str) -> Dict[str, Any]:
        """
        Tool 2: check_refund_eligibility
        Evaluates deterministic business rules against the fixed scenario clock.
        """
        order_dict = self.get_order(session_customer_id, order_id)
        order_status = order_dict["status"]
        delivery_date_str = order_dict["delivery_date"]

        # Rule 4: Already refunded order cannot be refunded again
        existing_refund = self.db.query(RefundRequest).filter(
            RefundRequest.order_id == order_id,
            RefundRequest.scenario_run_id == self.scenario_run_id
        ).first()

        if existing_refund or order_status == "REFUNDED":
            return {
                "order_id": order_id,
                "eligible": False,
                "reason_code": "ALREADY_REFUNDED",
                "message": "Order has already been refunded or has an active refund request pending.",
                "max_refundable_cents": 0
            }

        # Rule 5: Unknown or corrupted status requires investigation
        if order_status in ["UNKNOWN", "INVESTIGATION_REQUIRED"]:
            return {
                "order_id": order_id,
                "eligible": False,
                "reason_code": "NEEDS_VERIFICATION",
                "message": "Order status is irregular or unverified. Manual review required.",
                "max_refundable_cents": 0
            }

        # Rule 3: Cancelled orders are eligible for full refund
        if order_status == "CANCELLED":
            return {
                "order_id": order_id,
                "eligible": True,
                "reason_code": "CANCELLED_ORDER_ELIGIBLE",
                "message": "Order was cancelled before shipment; full refund is permitted.",
                "max_refundable_cents": order_dict["total_amount_cents"]
            }

        # Rule 2: Delivered order within 14 days
        if order_status == "DELIVERED":
            if not delivery_date_str:
                return {
                    "order_id": order_id,
                    "eligible": False,
                    "reason_code": "MISSING_DELIVERY_DATE",
                    "message": "Delivery timestamp is missing; requires verification.",
                    "max_refundable_cents": 0
                }

            delivery_dt = datetime.datetime.fromisoformat(delivery_date_str)
            days_elapsed = (self.fixed_clock - delivery_dt).total_seconds() / 86400.0

            if days_elapsed < 0:
                return {
                    "order_id": order_id,
                    "eligible": False,
                    "reason_code": "FUTURE_DELIVERY_DATE",
                    "message": "Delivery date is in the future relative to scenario clock.",
                    "max_refundable_cents": 0
                }

            if days_elapsed <= 14.0:
                remaining_days = round(14.0 - days_elapsed, 1)
                return {
                    "order_id": order_id,
                    "eligible": True,
                    "reason_code": "DELIVERED_WITHIN_WINDOW",
                    "message": f"Delivered {round(days_elapsed, 1)} days ago. Eligible within 14-day window ({remaining_days} days remaining).",
                    "max_refundable_cents": order_dict["total_amount_cents"]
                }
            else:
                return {
                    "order_id": order_id,
                    "eligible": False,
                    "reason_code": "RETURN_WINDOW_EXPIRED",
                    "message": f"Order was delivered {round(days_elapsed, 1)} days ago, which exceeds the 14-day refund window.",
                    "max_refundable_cents": 0
                }

        # Any other unfulfilled/processing status
        return {
            "order_id": order_id,
            "eligible": False,
            "reason_code": "ORDER_NOT_DELIVERED",
            "message": f"Order status is '{order_status}'. Only delivered or cancelled orders can be refunded.",
            "max_refundable_cents": 0
        }

    def request_refund(
        self,
        session_customer_id: str,
        order_id: str,
        amount_cents: int,
        operation_key: str,
        reason: Optional[str] = "Customer requested refund"
    ) -> Dict[str, Any]:
        """
        Tool 3: request_refund
        Enforces idempotency, full amount constraint, duplicate prevention, and saves record.
        """
        # Idempotency check: if operation_key already processed, verify payload matches
        existing_op = self.db.query(RefundRequest).filter(
            RefundRequest.operation_key == operation_key,
            RefundRequest.scenario_run_id == self.scenario_run_id
        ).first()

        if existing_op:
            if existing_op.order_id != order_id or existing_op.amount_cents != amount_cents:
                raise RefundDomainError(
                    code="IDEMPOTENCY_PAYLOAD_MISMATCH",
                    message=(
                        f"Operation key '{operation_key}' was previously processed with order '{existing_op.order_id}' "
                        f"and amount {existing_op.amount_cents} cents. Conflicting reuse with order '{order_id}' "
                        f"and amount {amount_cents} cents is rejected."
                    ),
                    status_code=409
                )

            return {
                "status": "SUCCESS",
                "refund_id": existing_op.id,
                "order_id": existing_op.order_id,
                "amount_cents": existing_op.amount_cents,
                "refund_status": existing_op.status,
                "idempotent_replay": True,
                "message": "Refund request was previously recorded with this operation key."
            }

        # 1. Ownership & order lookup
        order_dict = self.get_order(session_customer_id, order_id)

        # 2. Eligibility evaluation
        eligibility = self.check_refund_eligibility(session_customer_id, order_id)
        if not eligibility["eligible"]:
            raise RefundDomainError(
                code=f"INELIGIBLE_{eligibility['reason_code']}",
                message=f"Refund denied: {eligibility['message']}",
                status_code=400
            )

        # 3. Rule 7: No partial refunds in V1
        if amount_cents != order_dict["total_amount_cents"]:
            raise RefundDomainError(
                code="INVALID_AMOUNT",
                message=f"Requested amount ({amount_cents} cents) does not match full order total ({order_dict['total_amount_cents']} cents). Partial refunds not supported.",
                status_code=400
            )

        # 4. Check for duplicate order refund
        existing_refund = self.db.query(RefundRequest).filter(
            RefundRequest.order_id == order_id,
            RefundRequest.scenario_run_id == self.scenario_run_id
        ).first()

        if existing_refund:
            raise RefundDomainError(
                code="DUPLICATE_REFUND_REQUEST",
                message=f"Order '{order_id}' already has a refund request record '{existing_refund.id}'.",
                status_code=409
            )

        # 5. Create refund record with status 'REFUND_REQUESTED'
        refund_id = f"ref_{order_id}_{int(self.fixed_clock.timestamp())}"
        refund_record = RefundRequest(
            id=refund_id,
            scenario_run_id=self.scenario_run_id,
            order_id=order_id,
            amount_cents=amount_cents,
            status="REFUND_REQUESTED",
            operation_key=operation_key,
            reason=reason,
            created_at=self.fixed_clock
        )

        try:
            self.db.add(refund_record)
            self.db.commit()
            self.db.refresh(refund_record)
        except IntegrityError as e:
            self.db.rollback()
            raise RefundDomainError(
                code="DATABASE_CONSTRAINT_VIOLATION",
                message=f"Database constraint violation during refund creation: {str(e)}",
                status_code=409
            )

        return {
            "status": "SUCCESS",
            "refund_id": refund_record.id,
            "order_id": refund_record.order_id,
            "amount_cents": refund_record.amount_cents,
            "refund_status": refund_record.status,
            "idempotent_replay": False,
            "message": "Refund request successfully submitted for processing."
        }
