"""
Campaign P&L & COD Financial Aggregator Skill (Phase-4 Gold Tier).

Bridges Meta Ad Spend (from CampaignMetricsSnapshot) with actual e-commerce
order fulfillment and courier delivery/RTO outcomes (from Orders table).

Computes the "Money View" for Pakistani e-commerce merchants:
- Paper Meta ROAS vs Real Pocket ROAS
- Delivered Cash vs RTO Leakage
- Contribution Margin & True Net Profit per campaign
"""

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ad_account import AdAccount
from app.models.metrics import CampaignMetricsSnapshot
from app.models.order import Order


def compute_pnl_summary(
    campaign_spends: dict[str, dict[str, Any]],  # cid -> {"spend": Decimal, "name": str}
    orders: list[Any],  # list of Order objects or dicts
) -> dict[str, Any]:
    """
    Pure aggregation function computing per-campaign and tenant-wide P&L.

    Args:
        campaign_spends: Dict mapping campaign_id to dict with 'spend' and 'name'.
        orders: List of Order instances within the reporting window.

    Returns:
        Structured P&L dict with per-campaign metrics and global totals.
    """
    # Group orders by campaign_id
    orders_by_campaign: dict[str, list[Any]] = {}
    unattributed_orders: list[Any] = []

    for order in orders:
        cid = getattr(order, "campaign_id", None) or (order.get("campaign_id") if isinstance(order, dict) else None)
        if cid:
            orders_by_campaign.setdefault(str(cid), []).append(order)
        else:
            unattributed_orders.append(order)

    # Collect all campaign IDs
    all_cids = set(campaign_spends.keys()) | set(orders_by_campaign.keys())

    campaign_reports: list[dict[str, Any]] = []

    total_ad_spend = Decimal("0.00")
    total_delivered_revenue = Decimal("0.00")
    total_cogs = Decimal("0.00")
    total_courier_fees = Decimal("0.00")
    total_orders_count = 0
    total_delivered_count = 0
    total_returned_count = 0

    for cid in sorted(all_cids):
        camp_meta = campaign_spends.get(cid, {})
        spend = Decimal(str(camp_meta.get("spend", 0.00)))
        name = camp_meta.get("name") or f"Campaign {cid}"

        c_orders = orders_by_campaign.get(cid, [])
        order_count = len(c_orders)
        delivered_count = 0
        returned_count = 0
        in_transit_count = 0
        cancelled_count = 0

        delivered_rev = Decimal("0.00")
        cogs = Decimal("0.00")
        courier_fees = Decimal("0.00")

        for o in c_orders:
            st = (getattr(o, "current_status", None) or (o.get("current_status") if isinstance(o, dict) else "PENDING")).upper()
            tot = Decimal(str(getattr(o, "total_amount_pkr", None) or (o.get("total_amount_pkr", 0) if isinstance(o, dict) else 0)))
            cg = Decimal(str(getattr(o, "cogs_amount_pkr", None) or (o.get("cogs_amount_pkr", 0) if isinstance(o, dict) else 0)))
            d_fee = Decimal(str(getattr(o, "courier_fee_pkr", None) or (o.get("courier_fee_pkr", 0) if isinstance(o, dict) else 0)))
            r_fee = Decimal(str(getattr(o, "return_fee_pkr", None) or (o.get("return_fee_pkr", 0) if isinstance(o, dict) else 0)))

            if st == "DELIVERED":
                delivered_count += 1
                delivered_rev += tot
                cogs += cg
                courier_fees += d_fee
            elif st == "RETURNED":
                returned_count += 1
                courier_fees += (d_fee + r_fee)
            elif st == "CANCELLED":
                cancelled_count += 1
            else:
                in_transit_count += 1

        net_profit = delivered_rev - cogs - courier_fees - spend

        delivery_rate = round((delivered_count / order_count * 100), 2) if order_count > 0 else 0.0
        rto_rate = round((returned_count / order_count * 100), 2) if order_count > 0 else 0.0
        real_roas = round(float(delivered_rev / spend), 2) if spend > 0 else 0.0
        net_margin = round(float((net_profit / delivered_rev) * 100), 2) if delivered_rev > 0 else 0.0

        campaign_reports.append({
            "campaign_id": cid,
            "campaign_name": name,
            "ad_spend": float(spend),
            "total_orders": order_count,
            "delivered_orders": delivered_count,
            "returned_orders": returned_count,
            "in_transit_orders": in_transit_count,
            "cancelled_orders": cancelled_count,
            "delivery_rate_pct": delivery_rate,
            "rto_rate_pct": rto_rate,
            "delivered_revenue": float(delivered_rev),
            "cogs": float(cogs),
            "courier_fees": float(courier_fees),
            "net_profit": float(net_profit),
            "real_roas": real_roas,
            "net_margin_pct": net_margin,
            "is_profitable": net_profit > 0,
        })

        total_ad_spend += spend
        total_delivered_revenue += delivered_rev
        total_cogs += cogs
        total_courier_fees += courier_fees
        total_orders_count += order_count
        total_delivered_count += delivered_count
        total_returned_count += returned_count

    # Account for unattributed orders in total
    unattributed_delivered_rev = Decimal("0.00")
    for o in unattributed_orders:
        st = (getattr(o, "current_status", None) or (o.get("current_status") if isinstance(o, dict) else "PENDING")).upper()
        tot = Decimal(str(getattr(o, "total_amount_pkr", None) or (o.get("total_amount_pkr", 0) if isinstance(o, dict) else 0)))
        cg = Decimal(str(getattr(o, "cogs_amount_pkr", None) or (o.get("cogs_amount_pkr", 0) if isinstance(o, dict) else 0)))
        d_fee = Decimal(str(getattr(o, "courier_fee_pkr", None) or (o.get("courier_fee_pkr", 0) if isinstance(o, dict) else 0)))
        r_fee = Decimal(str(getattr(o, "return_fee_pkr", None) or (o.get("return_fee_pkr", 0) if isinstance(o, dict) else 0)))
        total_orders_count += 1
        if st == "DELIVERED":
            total_delivered_count += 1
            unattributed_delivered_rev += tot
            total_delivered_revenue += tot
            total_cogs += cg
            total_courier_fees += d_fee
        elif st == "RETURNED":
            total_returned_count += 1
            total_courier_fees += (d_fee + r_fee)

    total_net_profit = total_delivered_revenue - total_cogs - total_courier_fees - total_ad_spend
    blended_delivery_rate = round((total_delivered_count / total_orders_count * 100), 2) if total_orders_count > 0 else 0.0
    blended_rto_rate = round((total_returned_count / total_orders_count * 100), 2) if total_orders_count > 0 else 0.0
    blended_real_roas = round(float(total_delivered_revenue / total_ad_spend), 2) if total_ad_spend > 0 else 0.0
    blended_margin = round(float((total_net_profit / total_delivered_revenue) * 100), 2) if total_delivered_revenue > 0 else 0.0

    return {
        "campaigns": campaign_reports,
        "totals": {
            "total_ad_spend": float(total_ad_spend),
            "total_orders": total_orders_count,
            "total_delivered_orders": total_delivered_count,
            "total_returned_orders": total_returned_count,
            "blended_delivery_rate_pct": blended_delivery_rate,
            "blended_rto_rate_pct": blended_rto_rate,
            "total_delivered_revenue": float(total_delivered_revenue),
            "total_cogs": float(total_cogs),
            "total_courier_fees": float(total_courier_fees),
            "total_net_profit": float(total_net_profit),
            "blended_real_roas": blended_real_roas,
            "blended_net_margin_pct": blended_margin,
            "is_profitable": total_net_profit > 0,
        },
    }


async def fetch_and_compute_tenant_pnl(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """
    Fetch DB snapshots and orders for a tenant in the given date range,
    and compute full campaign P&L breakdown.
    """
    # 1. Fetch Ad Accounts for this tenant
    acc_res = await session.execute(
        select(AdAccount.id).where(AdAccount.tenant_id == tenant_id)
    )
    ad_account_ids = acc_res.scalars().all()

    # 2. Query ad spend by campaign from CampaignMetricsSnapshot
    campaign_spends: dict[str, dict[str, Any]] = {}
    if ad_account_ids:
        snap_res = await session.execute(
            select(
                CampaignMetricsSnapshot.external_campaign_id,
                func.max(CampaignMetricsSnapshot.campaign_name).label("name"),
                func.sum(CampaignMetricsSnapshot.spend).label("spend"),
            )
            .where(
                CampaignMetricsSnapshot.ad_account_id.in_(ad_account_ids),
                CampaignMetricsSnapshot.snapshot_date >= start_date,
                CampaignMetricsSnapshot.snapshot_date <= end_date,
            )
            .group_by(CampaignMetricsSnapshot.external_campaign_id)
        )
        for row in snap_res.all():
            cid = str(row.external_campaign_id)
            campaign_spends[cid] = {
                "name": row.name or f"Campaign {cid}",
                "spend": Decimal(str(row.spend or 0.00)),
            }

    # 3. Query orders created within the date window for this tenant
    start_dt = datetime.combine(start_date, time.min).replace(tzinfo=UTC)
    end_dt = datetime.combine(end_date, time.max).replace(tzinfo=UTC)

    ord_res = await session.execute(
        select(Order).where(
            Order.tenant_id == tenant_id,
            Order.order_date >= start_dt,
            Order.order_date <= end_dt,
        )
    )
    orders = ord_res.scalars().all()

    return compute_pnl_summary(campaign_spends=campaign_spends, orders=orders)
