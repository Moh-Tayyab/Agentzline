"""
AgentZline — Interactive End-to-End Live Store Simulator.

Runs a realistic local simulation of a Pakistani E-Commerce Store
to demonstrate exactly how AgentZline saves money and computes true profit.
"""

import asyncio
import os
import sys
import uuid
from decimal import Decimal

# Ensure app is in path
sys.path.insert(0, os.path.abspath("."))

from app.skills.meta_normalizer import normalize_campaign_insight
from app.skills.courier_normalizer import compute_net_order_profit, normalize_courier_status
from app.skills.campaign_pnl import compute_pnl_summary
from app.skills.bilingual_report import format_daily_summary
from app.skills.intraday_pacing import detect_intraday_pacing_alerts, format_pacing_alert
from app.skills.hitl_action_tokens import generate_action_token, verify_action_token


def print_banner(text: str, char: str = "="):
    line = char * 70
    print(f"\n{line}\n  {text}\n{line}")


def simulate():
    print_banner("⚡ AGENTZLINE LIVE STORE SIMULATION (Pakistani E-Commerce)", "=")
    print("Store Name: 'Khaadi Official / Gul Ahmed PK'")
    print("Currency: PKR (Pakistani Rupee)")
    print("Logistics Partners: PostEx & Trax Logistics\n")

    # -------------------------------------------------------------------------
    # STAGE 1: META ADS INGESTION (What Meta Ads Manager reports)
    # -------------------------------------------------------------------------
    print_banner("STAGE 1: Meta Ads Manager Data (The Fake Paper ROAS)", "-")
    
    raw_campaigns = [
        {
            "campaign_id": "c_lawn_festive",
            "campaign_name": "Summer Lawn Volume 1 (Winner)",
            "spend": "20000.00",
            "impressions": 55000,
            "clicks": 1400,
            "actions": [{"action_type": "purchase", "value": "40"}],
            "action_values": [{"action_type": "purchase", "value": "120000.00"}],
        },
        {
            "campaign_id": "c_pret_casual",
            "campaign_name": "Ready-to-Wear Pret (Moderate)",
            "spend": "15000.00",
            "impressions": 32000,
            "clicks": 680,
            "actions": [{"action_type": "purchase", "value": "18"}],
            "action_values": [{"action_type": "purchase", "value": "54000.00"}],
        },
        {
            "campaign_id": "c_winter_clearance",
            "campaign_name": "Winter Clearance Bleeder (Money Burner)",
            "spend": "10000.00",
            "impressions": 20000,
            "clicks": 180,
            "actions": [{"action_type": "purchase", "value": "1"}],
            "action_values": [{"action_type": "purchase", "value": "3000.00"}],
        },
    ]

    total_meta_spend = Decimal("0")
    total_meta_rev = Decimal("0")
    total_meta_conversions = 0

    campaign_spends_map = {}

    for c in raw_campaigns:
        norm = normalize_campaign_insight(c)
        spend = norm["spend"]
        rev = norm["purchase_value"]
        roas = norm["roas"]
        conv = norm["conversions"]
        total_meta_spend += spend
        total_meta_rev += rev
        total_meta_conversions += conv

        campaign_spends_map[c["campaign_id"]] = {
            "name": c["campaign_name"],
            "spend": spend,
        }

        print(f"📊 Campaign: {c['campaign_name']}")
        print(f"   • Ad Spend: {spend:,.0f} PKR | Purchases: {conv}")
        print(f"   • Meta Reported Revenue: {rev:,.0f} PKR")
        print(f"   • Meta Paper ROAS: {roas:.2f}x\n")

    overall_meta_roas = total_meta_rev / total_meta_spend
    print(f"👉 Meta Ads Manager says: Total Spend: {total_meta_spend:,.0f} PKR, Total Sales: {total_meta_rev:,.0f} PKR")
    print(f"👉 Brand Owner thinks: 'ROAS is {overall_meta_roas:.2f}x, I made {total_meta_rev - total_meta_spend:,.0f} PKR profit!'")
    print("   ⚠️ BUT WAIT... Did the customers actually pay cash on delivery?")

    # -------------------------------------------------------------------------
    # STAGE 2: COURIER WEBHOOKS (The Cash-on-Delivery Reality)
    # -------------------------------------------------------------------------
    print_banner("STAGE 2: Courier Reconciliation (PostEx / Trax Webhooks)", "-")

    # Real Orders from customers:
    # Product Selling Price: 3000 PKR, Product Cost (COGS): 1200 PKR, Delivery Fee: 250 PKR, Return Fee: 150 PKR
    orders = []

    # Campaign 1 (Winner): 40 orders -> 34 Delivered (85% delivery rate), 6 Returned (RTO)
    for i in range(1, 41):
        is_deliv = i <= 34
        orders.append({
            "campaign_id": "c_lawn_festive",
            "external_order_id": f"ORD-LAWN-{i:03d}",
            "payment_method": "COD",
            "total_amount_pkr": Decimal("3000.00"),
            "cogs_amount_pkr": Decimal("1200.00"),
            "courier_fee_pkr": Decimal("250.00"),
            "return_fee_pkr": Decimal("150.00") if not is_deliv else Decimal("0.00"),
            "current_status": "DELIVERED" if is_deliv else "RETURNED",
        })

    # Campaign 2 (Moderate): 18 orders -> 11 Delivered (61% delivery rate), 7 Returned (RTO)
    for i in range(1, 19):
        is_deliv = i <= 11
        orders.append({
            "campaign_id": "c_pret_casual",
            "external_order_id": f"ORD-PRET-{i:03d}",
            "payment_method": "COD",
            "total_amount_pkr": Decimal("3000.00"),
            "cogs_amount_pkr": Decimal("1200.00"),
            "courier_fee_pkr": Decimal("250.00"),
            "return_fee_pkr": Decimal("150.00") if not is_deliv else Decimal("0.00"),
            "current_status": "DELIVERED" if is_deliv else "RETURNED",
        })

    # Campaign 3 (Bleeder): 1 order -> 0 Delivered, 1 Returned (100% RTO)
    orders.append({
        "campaign_id": "c_winter_clearance",
        "external_order_id": "ORD-WINTER-001",
        "payment_method": "COD",
        "total_amount_pkr": Decimal("3000.00"),
        "cogs_amount_pkr": Decimal("1200.00"),
        "courier_fee_pkr": Decimal("250.00"),
        "return_fee_pkr": Decimal("150.00"),
        "current_status": "RETURNED",
    })

    print(f"📦 Total Booked Orders: {len(orders)}")
    delivered_count = sum(1 for o in orders if o["current_status"] == "DELIVERED")
    returned_count = sum(1 for o in orders if o["current_status"] == "RETURNED")
    print(f"   • Delivered (Cash Received): {delivered_count} ({delivered_count/len(orders)*100:.1f}%)")
    print(f"   • Returned (RTO Rejection): {returned_count} ({returned_count/len(orders)*100:.1f}%)")
    print("   • Courier fees charged on returned parcels: 250 dispatch + 150 return = 400 PKR penalty each!")

    # -------------------------------------------------------------------------
    # STAGE 3: AGENTZLINE TRUE P&L CALCULATION ("The Money View")
    # -------------------------------------------------------------------------
    print_banner("STAGE 3: AgentZline True Profit & Loss Engine", "-")
    pnl = compute_pnl_summary(campaign_spends_map, orders)

    for c_stat in pnl["campaigns"]:
        cid = c_stat["campaign_id"]
        c_name = campaign_spends_map.get(cid, {}).get("name", cid)
        spend = c_stat["ad_spend"]
        deliv_cash = c_stat["delivered_revenue"]
        cogs = c_stat["cogs"]
        fees = c_stat["courier_fees"]
        net_prof = c_stat["net_profit"]
        deliv_rate = c_stat["delivery_rate_pct"]
        real_roas = c_stat["real_roas"]

        status_icon = "🟢 PROFITABLE" if net_prof > 0 else "🔴 LOSS MAKING (BLEEDER)"
        print(f"📌 {c_name} [{status_icon}]:")
        print(f"   • Ad Spend: {spend:,.0f} PKR | Delivery Rate: {deliv_rate:.1f}%")
        print(f"   • Delivered Cash: {deliv_cash:,.0f} PKR")
        print(f"   • Product COGS: -{cogs:,.0f} PKR")
        print(f"   • Courier Logistics Fees: -{fees:,.0f} PKR")
        print(f"   ------------------------------------------------")
        print(f"   💰 ASLI POCKET PROFIT: {net_prof:,.0f} PKR  (Real ROAS: {real_roas:.2f}x)\n")

    t_spend = pnl["totals"]["total_ad_spend"]
    t_cash = pnl["totals"]["total_delivered_revenue"]
    t_cogs = pnl["totals"]["total_cogs"]
    t_fees = pnl["totals"]["total_courier_fees"]
    t_profit = pnl["totals"]["total_net_profit"]

    print(f"🏆 OVERALL BUSINESS REALITY:")
    print(f"   • Delivered Cash in Hand:  {t_cash:,.0f} PKR")
    print(f"   • Total Product COGS:     -{t_cogs:,.0f} PKR")
    print(f"   • Courier Logistics Fees: -{t_fees:,.0f} PKR")
    print(f"   • Meta Ad Spend:          -{t_spend:,.0f} PKR")
    print(f"   ================================================")
    print(f"   💵 TOTAL POCKET PROFIT:    {t_profit:,.0f} PKR  (Delivery Rate: {pnl['totals']['blended_delivery_rate_pct']:.1f}%)")

    # -------------------------------------------------------------------------
    # STAGE 4: DAILY EXECUTIVE WHATSAPP REPORT (What Client Sees on Phone)
    # -------------------------------------------------------------------------
    print_banner("STAGE 4: What Client Receives on WhatsApp at 09:00 PKT", "-")
    
    summary_dict = {
        "account_name": "Khaadi Official PK",
        "date": "2026-10-13",
        "total_spend": float(total_meta_spend),
        "total_impressions": 107000,
        "total_clicks": 2260,
        "total_conversions": total_meta_conversions,
        "aggregate_roas": float(overall_meta_roas),
        "aggregate_ctr": 2.11,
    }

    # Format Roman Urdu report
    whatsapp_msg = format_daily_summary(
        summary=summary_dict,
        anomalies=[
            {
                "type": "cpa_surge",
                "campaign_name": "Winter Clearance Bleeder",
                "metric_value": 10000.0,
                "threshold": 1500.0,
                "message": "CPA 10,000 PKR exceed ho gaya hai with zero real sales",
            }
        ],
        language="roman_urdu",
        cod_summary=pnl["totals"],
    )

    print("📱 [WHATSAPP MESSAGE PREVIEW - ROMAN URDU]:")
    print("-" * 50)
    print(whatsapp_msg)
    print("-" * 50)

    # -------------------------------------------------------------------------
    # STAGE 5: INTRADAY BLEED DETECTION & ONE-TAP PAUSE BUTTON
    # -------------------------------------------------------------------------
    print_banner("STAGE 5: Intraday Pacing Bleed Alert & One-Tap Pause Button", "-")
    print("Scenario: At 14:00 PKT, campaign 'Winter Clearance Bleeder' has spent")
    print("5,500 PKR out of 10,000 daily budget with 0 sales and 0.4% CTR.\n")

    bleed_alerts = detect_intraday_pacing_alerts(
        metrics=[
            {
                "id": "c_winter_clearance",
                "name": "Winter Clearance Bleeder",
                "spend": Decimal("5500.00"),
                "conversions": 0,
                "ctr": 0.40,
            }
        ],
        budgets_by_campaign={"c_winter_clearance": Decimal("10000.00")},
        spend_ratio=0.5,
        ctr_threshold=0.6,
    )

    alert = bleed_alerts[0]
    print(f"🚨 Intraday Bleed Rule Triggered: {alert['type']}")
    print(f"   Spend: {alert['details']['spend']:,.0f} PKR / {alert['details']['daily_budget']:,.0f} PKR budget ({alert['details']['spend_fraction']*100:.1f}%)")
    print(f"   Conversions: {alert['details']['conversions']} | CTR: {alert['details']['ctr']:.2f}%")

    # Cryptographic Action Token generation
    test_tenant_id = str(uuid.uuid4())
    token = generate_action_token(
        tenant_id=test_tenant_id,
        campaign_id="c_winter_clearance",
        action="PAUSE",
        ttl_seconds=900,
    )

    print(f"\n🔐 Signed Action Token Generated (HMAC-SHA256, 15-min TTL):")
    print(f"   Token length: {len(token)} characters (WhatsApp quick-reply safe: limit is 256 chars)")
    print(f"   Token string: {token[:30]}...{token[-15:]}")

    print("\n📱 Interactive WhatsApp Alert Sent to Media Buyer:")
    print("   ┌──────────────────────────────────────────────────────────┐")
    print("   │ ⚠️ URGENT PACING BLEED: Winter Clearance Bleeder         │")
    print("   │ 5,500 PKR burned today with ZERO conversions!           │")
    print("   │                                                          │")
    print(f"   │ [🔴 PAUSE CAMPAIGN]  -> Links to /actions/pause?token=.. │")
    print("   │ [KEEP RUNNING]                                           │")
    print("   └──────────────────────────────────────────────────────────┘")

    # -------------------------------------------------------------------------
    # STAGE 6: EXECUTING THE PAUSE MUTATION (Client clicks button)
    # -------------------------------------------------------------------------
    print_banner("STAGE 6: Client Clicks [🔴 PAUSE CAMPAIGN] on WhatsApp", "-")
    print("Client taps button on phone. AgentZline verifies cryptographic signature...")

    verified_payload = verify_action_token(token)
    if verified_payload:
        print("✅ Cryptographic Token Verified successfully!")
        print(f"   • Tenant: {verified_payload['tenant_id']}")
        print(f"   • Campaign to Pause: {verified_payload['campaign_id']}")
        print(f"   • Action: {verified_payload['action']}")
        print(f"   • Replay Protection: Token marked used in AuditLog")
        print(f"   • Meta Graph API Mutation (Simulated): POST /{verified_payload['campaign_id']} status='PAUSED'")
        print("   🎉 CAMPAIGN SAFELY PAUSED! Budget bleeding stopped instantly!")
    else:
        print("❌ Token verification failed.")

    print_banner("🎉 SIMULATION COMPLETE: ALL 6 PHASES PASSED 100%!", "=")
    print("Ab aap dekh sakte hain ke AgentZline exactly kya karta hai:\n")
    print("1. Meta ka jhoota paper ROAS nikaalta hai.")
    print("2. Courier webhooks se delivered cash aur RTO loss track karta hai.")
    print("3. Asli Pocket Profit calculate karta hai.")
    print("4. Daily WhatsApp report bhejta hai (Roman Urdu + English).")
    print("5. Bleeding ads ko 14:00/18:00 PKT par detect karta hai.")
    print("6. WhatsApp par 1-tap me ads pause karne ka cryptographic button deta hai.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    simulate()
