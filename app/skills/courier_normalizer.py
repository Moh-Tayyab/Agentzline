"""
Courier Status Normalization & Financial Skill (Phase-4 Gold Tier).

Standardizes multi-courier webhook payloads (starting with PostEx MVP)
into canonical delivery lifecycles and computes real net profit accounting
for COD returns (RTO) and courier penalties.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from loguru import logger


CANONICAL_STATUSES = {
    "BOOKED",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "RETURNED",
    "CANCELLED",
    "UNKNOWN",
}

# PostEx status name -> Canonical status
POSTEX_NAME_MAP: dict[str, str] = {
    "order placed": "BOOKED",
    "un-assigned": "BOOKED",
    "assigned": "BOOKED",
    "booked": "BOOKED",
    "manifested": "BOOKED",
    "picked up": "IN_TRANSIT",
    "arrived at station": "IN_TRANSIT",
    "in transit": "IN_TRANSIT",
    "en route": "IN_TRANSIT",
    "transfer": "IN_TRANSIT",
    "out for delivery": "OUT_FOR_DELIVERY",
    "delivery scheduled": "OUT_FOR_DELIVERY",
    "delivered": "DELIVERED",
    "delivered to customer": "DELIVERED",
    "completed": "DELIVERED",
    "returned": "RETURNED",
    "returned to merchant": "RETURNED",
    "rto": "RETURNED",
    "delivery attempt failed": "RETURNED",
    "return in transit": "RETURNED",
    "delivery failed": "RETURNED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "returned before delivery": "CANCELLED",
}

# PostEx integer code -> Canonical status
POSTEX_CODE_MAP: dict[int, str] = {
    1: "BOOKED",
    2: "IN_TRANSIT",
    3: "OUT_FOR_DELIVERY",
    4: "DELIVERED",
    5: "RETURNED",
    6: "CANCELLED",
}


# Trax status name -> Canonical status
TRAX_NAME_MAP: dict[str, str] = {
    "booking created": "BOOKED",
    "pickup scheduled": "BOOKED",
    "booked": "BOOKED",
    "picked up": "IN_TRANSIT",
    "in transit": "IN_TRANSIT",
    "received at station": "IN_TRANSIT",
    "departed from station": "IN_TRANSIT",
    "out for delivery": "OUT_FOR_DELIVERY",
    "rider assigned": "OUT_FOR_DELIVERY",
    "delivered": "DELIVERED",
    "delivery completed": "DELIVERED",
    "returned to shipper": "RETURNED",
    "return completed": "RETURNED",
    "failed delivery": "RETURNED",
    "rto": "RETURNED",
    "cancelled": "CANCELLED",
    "void": "CANCELLED",
}

# Leopards status name -> Canonical status
LEOPARDS_NAME_MAP: dict[str, str] = {
    "booked": "BOOKED",
    "manifested": "BOOKED",
    "packet booked": "BOOKED",
    "in transit": "IN_TRANSIT",
    "dispatched": "IN_TRANSIT",
    "received at hub": "IN_TRANSIT",
    "out for delivery": "OUT_FOR_DELIVERY",
    "delivered": "DELIVERED",
    "returned": "RETURNED",
    "return to consignor": "RETURNED",
    "return to shipper": "RETURNED",
    "rts": "RETURNED",
    "cancelled": "CANCELLED",
}

# Swyft status name -> Canonical status
SWYFT_NAME_MAP: dict[str, str] = {
    "order_created": "BOOKED",
    "booking_confirmed": "BOOKED",
    "created": "BOOKED",
    "picked_up": "IN_TRANSIT",
    "in_transit": "IN_TRANSIT",
    "hub_transfer": "IN_TRANSIT",
    "out_for_delivery": "OUT_FOR_DELIVERY",
    "delivered": "DELIVERED",
    "returned": "RETURNED",
    "rto": "RETURNED",
    "rejected": "RETURNED",
    "cancelled": "CANCELLED",
}


def normalize_courier_status(courier: str, raw_status: Any) -> str:
    """
    Normalize raw courier status string or integer code to canonical status.

    Args:
        courier: Courier identifier ('POSTEX', 'TRAX', 'LEOPARDS', 'SWYFT').
        raw_status: Raw status value from webhook.

    Returns:
        Canonical status (BOOKED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, RETURNED, CANCELLED).
    """
    courier_norm = courier.strip().upper()
    if raw_status is None:
        return "UNKNOWN"

    # Numeric code lookup (PostEx)
    if isinstance(raw_status, int) or (isinstance(raw_status, str) and raw_status.isdigit()):
        code = int(raw_status)
        if courier_norm == "POSTEX":
            return POSTEX_CODE_MAP.get(code, "UNKNOWN")

    status_str = str(raw_status).strip().lower()

    if courier_norm == "POSTEX":
        return POSTEX_NAME_MAP.get(status_str, "UNKNOWN")
    elif courier_norm == "TRAX":
        return TRAX_NAME_MAP.get(status_str, "UNKNOWN")
    elif courier_norm == "LEOPARDS":
        return LEOPARDS_NAME_MAP.get(status_str, "UNKNOWN")
    elif courier_norm == "SWYFT":
        return SWYFT_NAME_MAP.get(status_str, "UNKNOWN")

    # Generic fallback
    if "deliver" in status_str and "out" not in status_str:
        return "DELIVERED"
    if "return" in status_str or "rto" in status_str or "rts" in status_str:
        return "RETURNED"
    if "out for" in status_str or "rider" in status_str:
        return "OUT_FOR_DELIVERY"
    if "transit" in status_str or "pickup" in status_str or "picked" in status_str or "hub" in status_str:
        return "IN_TRANSIT"
    if "cancel" in status_str or "void" in status_str:
        return "CANCELLED"
    if "book" in status_str or "place" in status_str or "create" in status_str:
        return "BOOKED"

    return "UNKNOWN"


def parse_postex_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a PostEx webhook payload into a normalized structure.

    Extracts: tracking_number, order_reference, raw_status,
    normalized_status, delivery_charges, return_charges, and timestamp.
    """
    tracking = (
        payload.get("trackingNumber")
        or payload.get("tracking_number")
        or payload.get("trackingNo")
        or payload.get("airwayBillNumber")
    )
    if tracking:
        tracking = str(tracking).strip()

    order_ref = (
        payload.get("orderRefNumber")
        or payload.get("order_ref_number")
        or payload.get("orderReference")
        or payload.get("orderId")
        or payload.get("external_order_id")
    )
    if order_ref:
        order_ref = str(order_ref).strip()

    raw_status = (
        payload.get("transactionStatus")
        or payload.get("orderStatus")
        or payload.get("status")
        or payload.get("orderStatusId")
    )
    norm_status = normalize_courier_status("POSTEX", raw_status)

    delivery_raw = (
        payload.get("invoiceDeliveryCharges")
        or payload.get("deliveryCharges")
        or payload.get("courier_fee")
        or 0
    )
    return_raw = (
        payload.get("invoiceReturnCharges")
        or payload.get("returnCharges")
        or payload.get("return_fee")
        or 0
    )

    try:
        delivery_charges = Decimal(str(delivery_raw)).quantize(Decimal("0.01"))
    except Exception:
        delivery_charges = Decimal("0.00")

    try:
        return_charges = Decimal(str(return_raw)).quantize(Decimal("0.01"))
    except Exception:
        return_charges = Decimal("0.00")

    ts_raw = payload.get("transactionTimestamp") or payload.get("timestamp")
    timestamp = datetime.now(timezone.utc)
    if ts_raw:
        try:
            if isinstance(ts_raw, str):
                timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except Exception:
            pass

    return {
        "courier_name": "POSTEX",
        "tracking_number": tracking,
        "order_reference": order_ref,
        "raw_status": str(raw_status or ""),
        "normalized_status": norm_status,
        "delivery_charges": delivery_charges,
        "return_charges": return_charges,
        "timestamp": timestamp,
    }


def parse_trax_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a Trax Logistics webhook payload into normalized structure."""
    tracking = (
        payload.get("tracking_number")
        or payload.get("trackingNumber")
        or payload.get("consignment_number")
    )
    if tracking:
        tracking = str(tracking).strip()

    order_ref = (
        payload.get("order_id")
        or payload.get("orderId")
        or payload.get("order_number")
        or payload.get("order_reference")
    )
    if order_ref:
        order_ref = str(order_ref).strip()

    raw_status = payload.get("status") or payload.get("tracking_status")
    norm_status = normalize_courier_status("TRAX", raw_status)

    delivery_raw = payload.get("charges") or payload.get("delivery_fee") or 0
    return_raw = payload.get("return_charges") or payload.get("return_fee") or 0

    try:
        delivery_charges = Decimal(str(delivery_raw)).quantize(Decimal("0.01"))
    except Exception:
        delivery_charges = Decimal("0.00")

    try:
        return_charges = Decimal(str(return_raw)).quantize(Decimal("0.01"))
    except Exception:
        return_charges = Decimal("0.00")

    ts_raw = payload.get("timestamp") or payload.get("date")
    timestamp = datetime.now(timezone.utc)
    if ts_raw:
        try:
            if isinstance(ts_raw, str):
                timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except Exception:
            pass

    return {
        "courier_name": "TRAX",
        "tracking_number": tracking,
        "order_reference": order_ref,
        "raw_status": str(raw_status or ""),
        "normalized_status": norm_status,
        "delivery_charges": delivery_charges,
        "return_charges": return_charges,
        "timestamp": timestamp,
    }


def parse_leopards_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a Leopards Courier webhook payload into normalized structure."""
    tracking = (
        payload.get("consignment_no")
        or payload.get("tracking_number")
        or payload.get("cn_number")
    )
    if tracking:
        tracking = str(tracking).strip()

    order_ref = (
        payload.get("booked_packet_order_id")
        or payload.get("order_id")
        or payload.get("order_reference")
    )
    if order_ref:
        order_ref = str(order_ref).strip()

    raw_status = payload.get("status") or payload.get("shipment_status")
    norm_status = normalize_courier_status("LEOPARDS", raw_status)

    delivery_raw = payload.get("delivery_charges") or payload.get("charges") or 0
    return_raw = payload.get("return_charges") or 0

    try:
        delivery_charges = Decimal(str(delivery_raw)).quantize(Decimal("0.01"))
    except Exception:
        delivery_charges = Decimal("0.00")

    try:
        return_charges = Decimal(str(return_raw)).quantize(Decimal("0.01"))
    except Exception:
        return_charges = Decimal("0.00")

    ts_raw = payload.get("activity_date") or payload.get("timestamp")
    timestamp = datetime.now(timezone.utc)
    if ts_raw:
        try:
            if isinstance(ts_raw, str):
                timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except Exception:
            pass

    return {
        "courier_name": "LEOPARDS",
        "tracking_number": tracking,
        "order_reference": order_ref,
        "raw_status": str(raw_status or ""),
        "normalized_status": norm_status,
        "delivery_charges": delivery_charges,
        "return_charges": return_charges,
        "timestamp": timestamp,
    }


def parse_swyft_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a Swyft Logistics webhook payload into normalized structure."""
    tracking = (
        payload.get("tracking_code")
        or payload.get("tracking_number")
        or payload.get("parcel_id")
    )
    if tracking:
        tracking = str(tracking).strip()

    order_ref = (
        payload.get("reference_id")
        or payload.get("order_id")
        or payload.get("order_number")
    )
    if order_ref:
        order_ref = str(order_ref).strip()

    raw_status = payload.get("status") or payload.get("state")
    norm_status = normalize_courier_status("SWYFT", raw_status)

    delivery_raw = payload.get("shipping_fee") or payload.get("delivery_fee") or 0
    return_raw = payload.get("return_fee") or 0

    try:
        delivery_charges = Decimal(str(delivery_raw)).quantize(Decimal("0.01"))
    except Exception:
        delivery_charges = Decimal("0.00")

    try:
        return_charges = Decimal(str(return_raw)).quantize(Decimal("0.01"))
    except Exception:
        return_charges = Decimal("0.00")

    ts_raw = payload.get("created_at") or payload.get("timestamp")
    timestamp = datetime.now(timezone.utc)
    if ts_raw:
        try:
            if isinstance(ts_raw, str):
                timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except Exception:
            pass

    return {
        "courier_name": "SWYFT",
        "tracking_number": tracking,
        "order_reference": order_ref,
        "raw_status": str(raw_status or ""),
        "normalized_status": norm_status,
        "delivery_charges": delivery_charges,
        "return_charges": return_charges,
        "timestamp": timestamp,
    }


def compute_net_order_profit(
    status: str,
    total_amount_pkr: Decimal | float,
    cogs_amount_pkr: Decimal | float,
    courier_fee_pkr: Decimal | float,
    return_fee_pkr: Decimal | float,
    allocated_ad_spend_pkr: Decimal | float = Decimal("0.00"),
) -> dict[str, Any]:
    """
    Calculate true net profit for an e-commerce order under Pakistani COD realities.

    Rules:
    - DELIVERED: Cash is collected (Revenue = total_amount), COGS and courier fees apply.
    - RETURNED (RTO): Revenue = 0. Merchant loses courier delivery + return penalty fee.
    - CANCELLED / PENDING / IN_TRANSIT: In-flight or cancelled (Revenue = 0, no COD settlement yet).

    Returns:
        Dict with delivered_revenue, cogs, total_fees, net_profit, and profit_status.
    """
    total = Decimal(str(total_amount_pkr))
    cogs = Decimal(str(cogs_amount_pkr))
    delivery_fee = Decimal(str(courier_fee_pkr))
    return_fee = Decimal(str(return_fee_pkr))
    ad_spend = Decimal(str(allocated_ad_spend_pkr))

    status_norm = status.strip().upper()

    if status_norm == "DELIVERED":
        revenue = total
        total_courier_fees = delivery_fee
        total_cost = cogs + total_courier_fees + ad_spend
        net_profit = revenue - total_cost
        margin_pct = float((net_profit / revenue) * 100) if revenue > 0 else 0.0
    elif status_norm == "RETURNED":
        revenue = Decimal("0.00")
        # In RTO, product is returned (no COGS lost unless damaged), but courier return penalty applies
        total_courier_fees = delivery_fee + return_fee
        total_cost = total_courier_fees + ad_spend
        net_profit = -total_cost
        margin_pct = -100.0
    else:
        # IN_TRANSIT / BOOKED / PENDING
        revenue = Decimal("0.00")
        total_courier_fees = Decimal("0.00")
        total_cost = ad_spend
        net_profit = -ad_spend
        margin_pct = 0.0

    return {
        "status": status_norm,
        "delivered_revenue": float(revenue),
        "cogs": float(cogs),
        "courier_fees": float(total_courier_fees),
        "allocated_ad_spend": float(ad_spend),
        "net_profit": float(net_profit),
        "margin_percentage": round(margin_pct, 2),
        "is_profitable": net_profit > 0,
    }
