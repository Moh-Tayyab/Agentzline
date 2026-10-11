"""
AgentZline Report Scheduler.

Schedules the daily Bronze Tier pipeline to run at the configured time
(default: 9:00 AM PKT / Asia/Karachi).
"""

import asyncio
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.core.security import decrypt_token
from app.models.tenant import Tenant
from app.models.credential import PlatformCredential
from app.models.audit_log import AuditLog
from app.agents.state import BronzeAgentState
from app.agents.graph import build_bronze_graph
from app.utils.meta_client import MetaAPIError, MetaGraphClient
from app.utils.whatsapp_client import WhatsAppClient
from app.skills.meta_normalizer import normalize_campaign_insight
from app.skills.intraday_pacing import (
    detect_intraday_pacing_alerts,
    format_pacing_alert,
    get_cached_budget,
    parse_meta_budget_to_pkr,
    set_cached_budget,
)
from app.skills.hitl_action_tokens import generate_action_token

scheduler = AsyncIOScheduler()


async def _process_tenant_report(
    tenant: Tenant,
    pipeline: Any,
    semaphore: asyncio.Semaphore,
    max_jitter: float,
    is_test_env: bool,
) -> None:
    """Process daily report workflow for a single tenant under bounded concurrency."""
    active_account_ids = [
        acc.external_account_id
        for acc in tenant.ad_accounts
        if acc.is_active
    ]

    if not active_account_ids:
        logger.info(f"⏭️ Skipping tenant {tenant.id} ({tenant.company_name}): No active ad accounts.")
        return

    if not tenant.whatsapp_notification_number:
        logger.warning(
            f"⚠️ Tenant {tenant.id} ({tenant.company_name}) has no WhatsApp notification number configured."
        )
        return

    # Independent stagger per tenant to spread traffic across jitter window
    if max_jitter > 0:
        jitter_seconds = random.uniform(0.01 if is_test_env else 1.0, max_jitter)
        logger.debug(f"⏳ Jitter delay {jitter_seconds:.2f}s for tenant {tenant.company_name}")
        await asyncio.sleep(jitter_seconds)

    async with semaphore:
        # Per-tenant vault resolution
        meta_token = None
        whatsapp_token = None
        for cred in getattr(tenant, "credentials", []):
            if cred.token_status == "ACTIVE":
                if cred.platform_name == "META" and cred.encrypted_access_token:
                    try:
                        meta_token = decrypt_token(cred.encrypted_access_token)
                    except Exception as err:
                        logger.error(f"Failed to decrypt Meta token for tenant {tenant.id}: {err}")
                elif cred.platform_name == "WHATSAPP" and cred.encrypted_access_token:
                    try:
                        whatsapp_token = decrypt_token(cred.encrypted_access_token)
                    except Exception as err:
                        logger.error(f"Failed to decrypt WhatsApp token for tenant {tenant.id}: {err}")

        logger.info(
            f"🚀 Running Bronze Tier pipeline for {tenant.company_name} "
            f"({len(active_account_ids)} accounts, custom_meta_token={'YES' if meta_token else 'NO'})"
        )

        state: BronzeAgentState = {
            "tenant_id": str(tenant.id),
            "ad_account_ids": active_account_ids,
            "target_date": date.today().isoformat(),
            "raw_metrics": [],
            "normalized_metrics": [],
            "daily_summary": {},
            "anomalies": [],
            "report_text": "",
            "recipient_whatsapp": tenant.whatsapp_notification_number,
            "language": tenant.preferred_language or "roman_urdu",
            "meta_access_token": meta_token,
            "whatsapp_access_token": whatsapp_token,
            "audit_actions": [],
            "errors": [],
        }

        try:
            final_state = await pipeline.ainvoke(state)
            logger.info(
                f"✅ Completed pipeline for {tenant.company_name}: "
                f"{len(final_state.get('audit_actions', []))} audit actions, "
                f"{len(final_state.get('errors', []))} errors."
            )

            # Persist audit actions to database
            async with async_session_maker() as audit_session:
                for action in final_state.get("audit_actions", []):
                    audit_entry = AuditLog(
                        tenant_id=tenant.id,
                        action_type=action.get("action_type", "REPORT_GEN"),
                        action_details=action,
                        executed_by="AGENTZLINE_SCHEDULER",
                        executed_by_whatsapp_num=tenant.whatsapp_notification_number,
                    )
                    audit_session.add(audit_entry)
                await audit_session.commit()
        except Exception as exc:
            logger.error(f"❌ Failed to run daily report for tenant {tenant.id}: {exc}")


async def run_daily_report_job():
    """
    Scheduled job: Run the Bronze Tier daily report for all active tenants.

    Uses bounded concurrency (Semaphore=5) and independent tenant jitter
    so 50+ clients complete within the 5-minute window without serialized 2-hour delays.
    """
    logger.info("⏰ Daily report job triggered")

    async with async_session_maker() as session:
        result = await session.execute(
            select(Tenant).options(
                selectinload(Tenant.ad_accounts),
                selectinload(Tenant.credentials),
            )
        )
        tenants = result.scalars().all()

        if not tenants:
            logger.info("ℹ️ No tenants registered for daily reports.")
            return

        pipeline = build_bronze_graph()
        settings = get_settings()
        is_test_env = (
            settings.APP_ENV == "test"
            or "sqlite" in settings.DATABASE_URL
            or "test" in settings.DATABASE_URL
        )
        max_jitter = 0.05 if is_test_env else float(settings.SCHEDULER_JITTER_MAX_SECONDS)

        # Semaphore(5) ensures max 5 simultaneous Meta/WhatsApp requests
        semaphore = asyncio.Semaphore(5)
        tasks = [
            _process_tenant_report(tenant, pipeline, semaphore, max_jitter, is_test_env)
            for tenant in tenants
        ]
        await asyncio.gather(*tasks)


def _build_expiry_message(platform: str, days_left: int, language: str) -> str:
    """Bilingual token-expiry warning text (Roman Urdu / English)."""
    if language == "english":
        return (
            f"⚠️ *Connection Alert — {platform}*\n"
            f"Your {platform} connection expires in *{days_left} day(s)*. "
            f"Re-authenticate now so daily reporting does not pause."
        )
    return (
        f"⚠️ *Connection Alert: {platform}*\n"
        f"Aapka {platform} connection *{days_left} din* mein expire ho raha hai. "
        f"Re-authenticate karein taake daily reporting pause na ho."
    )


async def run_token_expiry_watchdog() -> dict[str, int]:
    """
    Phase-1 Task #2: Proactive token expiry watchdog (midnight run).

    - Warns when an ACTIVE credential expires within TOKEN_EXPIRY_WARNING_DAYS.
    - Marks past-due credentials as EXPIRED.
    - Sends bilingual WhatsApp alerts and records AuditLog entries
      (TOKEN_EXPIRY_WARNING / TOKEN_EXPIRED).
    """
    settings = get_settings()
    warning_days = int(settings.TOKEN_EXPIRY_WARNING_DAYS)
    now = datetime.now(timezone.utc)
    stats = {"warned": 0, "expired": 0, "checked": 0}

    async with async_session_maker() as session:
        result = await session.execute(
            select(PlatformCredential).where(PlatformCredential.token_status == "ACTIVE")
        )
        creds = result.scalars().all()
        # Re-query tenants with notification numbers in one go
        tenant_ids = {cred.tenant_id for cred in creds}
        tenant_map: dict[str, Tenant] = {}
        if tenant_ids:
            t_res = await session.execute(
                select(Tenant)
                .where(Tenant.id.in_(tenant_ids))
                .options(selectinload(Tenant.credentials))
            )
            for t in t_res.scalars().all():
                tenant_map[str(t.id)] = t

        for cred in creds:
            if cred.expires_at is None:
                continue  # permanent token (e.g. WhatsApp) — no expiry
            stats["checked"] += 1
            expires_at = cred.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            days_left = (expires_at - now).days
            tenant = tenant_map.get(str(cred.tenant_id))

            if expires_at <= now:
                cred.token_status = "EXPIRED"
                stats["expired"] += 1
                session.add(AuditLog(
                    tenant_id=cred.tenant_id,
                    action_type="TOKEN_EXPIRED",
                    action_details={
                        "credential_id": str(cred.id),
                        "platform": cred.platform_name,
                        "expires_at": expires_at.isoformat(),
                    },
                    executed_by="AGENTZLINE_WATCHDOG",
                ))
                logger.warning(f"🔴 Credential {cred.id} ({cred.platform_name}) expired — marked EXPIRED")
                continue

            if days_left <= warning_days:
                stats["warned"] += 1
                session.add(AuditLog(
                    tenant_id=cred.tenant_id,
                    action_type="TOKEN_EXPIRY_WARNING",
                    action_details={
                        "credential_id": str(cred.id),
                        "platform": cred.platform_name,
                        "days_left": days_left,
                        "expires_at": expires_at.isoformat(),
                    },
                    executed_by="AGENTZLINE_WATCHDOG",
                ))
                # WhatsApp alert (best-effort; never fail the watchdog on send errors)
                if tenant is not None and tenant.whatsapp_notification_number:
                    language = tenant.preferred_language or "roman_urdu"
                    message = _build_expiry_message(cred.platform_name, days_left, language)
                    # Resolve per-tenant WhatsApp token, fallback to global default
                    wa_token = None
                    for c in getattr(tenant, "credentials", []):
                        if c.platform_name == "WHATSAPP" and c.token_status == "ACTIVE":
                            try:
                                wa_token = decrypt_token(c.encrypted_access_token)
                            except Exception:
                                wa_token = None
                            break
                    wa_client = WhatsAppClient(access_token=wa_token)
                    try:
                        await wa_client.send_text_message(
                            recipient_number=tenant.whatsapp_notification_number,
                            message_text=message,
                        )
                        logger.info(f"📤 Expiry warning sent to {tenant.company_name} ({days_left}d left)")
                    except Exception as exc:
                        logger.error(f"Failed to send expiry warning to {tenant.id}: {exc}")
                    finally:
                        await wa_client.close()
                else:
                    logger.warning(f"⚠️ No WhatsApp number for tenant {cred.tenant_id} — warning logged only")

        await session.commit()
    logger.info(f"🛡️ Watchdog done: {stats}")
    return stats


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive DB datetime to UTC-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _recently_alerted_campaigns(
    session: Any,
    tenant_id: Any,
    window_start: datetime,
) -> set[str]:
    """
    Return campaign ids already sent an INTRADAY_PACING_ALERT for this tenant
    within the suppression window (Python-side filter for PG/SQLite compat).
    """
    res = await session.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.action_type == "INTRADAY_PACING_ALERT",
        )
    )
    seen: set[str] = set()
    for entry in res.scalars().all():
        created = _as_utc(entry.created_at)
        if created is None or created < window_start:
            continue
        details = entry.action_details or {}
        cid = details.get("campaign_id")
        if cid:
            seen.add(str(cid))
    return seen


async def _process_tenant_pacing(
    tenant_id: Any,
    semaphore: asyncio.Semaphore,
    max_jitter: float,
    is_test_env: bool,
    settings: Any,
) -> dict[str, int]:
    """Run one tenant's intraday pacing check under bounded concurrency."""
    stats = {"alerts": 0, "skipped_suppressed": 0, "errors": 0}

    async with async_session_maker() as session:
        # Load everything needed in the worker's own session (no detached instances)
        t_res = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .options(selectinload(Tenant.ad_accounts), selectinload(Tenant.credentials))
        )
        full_tenant = t_res.scalars().first()
        if full_tenant is None:
            return stats
        if not full_tenant.whatsapp_notification_number:
            return stats
        active_accounts = [a for a in full_tenant.ad_accounts if a.is_active]
        if not active_accounts:
            return stats

        meta_token = None
        wa_token = None
        for c in full_tenant.credentials:
            if c.token_status != "ACTIVE":
                continue
            if c.platform_name == "META" and meta_token is None:
                try:
                    meta_token = decrypt_token(c.encrypted_access_token)
                except Exception as err:
                    logger.error(f"Failed to decrypt Meta token for tenant {tenant_id}: {err}")
            elif c.platform_name == "WHATSAPP" and wa_token is None:
                try:
                    wa_token = decrypt_token(c.encrypted_access_token)
                except Exception as err:
                    logger.error(f"Failed to decrypt WhatsApp token for tenant {tenant_id}: {err}")

        if max_jitter > 0:
            await asyncio.sleep(random.uniform(0.01 if is_test_env else 1.0, max_jitter))

        async with semaphore:
            today = date.today()
            meta_client = MetaGraphClient(access_token=meta_token)
            raw_insights: list[dict] = []
            campaign_ids: set[str] = set()
            try:
                for acc in active_accounts:
                    try:
                        insights = await meta_client.get_account_insights(
                            ad_account_id=acc.external_account_id,
                            date_start=today,
                            date_end=today,
                        )
                        raw_insights.extend(insights)
                    except MetaAPIError as err:
                        logger.error(f"Pacing fetch failed for {acc.external_account_id}: {err}")
                        stats["errors"] += 1
            finally:
                await meta_client.close()

            if not raw_insights:
                return stats

            normalized = [normalize_campaign_insight(r) for r in raw_insights]
            for n in normalized:
                if n.get("id"):
                    campaign_ids.add(str(n["id"]))

            # Resolve daily budgets (cached to avoid redundant Meta API calls across sweeps)
            budgets: dict[str, Decimal] = {}
            missing_cids: list[str] = []
            for cid in campaign_ids:
                cached_b = get_cached_budget(cid)
                if cached_b is not None:
                    budgets[cid] = cached_b
                else:
                    missing_cids.append(cid)

            if missing_cids:
                budget_client = MetaGraphClient(access_token=meta_token)
                try:
                    for cid in missing_cids:
                        try:
                            details = await budget_client.get_campaign_details(campaign_id=cid)
                            parsed = parse_meta_budget_to_pkr(details.get("daily_budget"))
                            if parsed is not None and parsed > Decimal("0"):
                                budgets[cid] = parsed
                                set_cached_budget(cid, parsed)
                        except MetaAPIError as err:
                            logger.warning(f"Budget lookup failed for campaign {cid}: {err}")
                finally:
                    await budget_client.close()

            alerts = detect_intraday_pacing_alerts(
                metrics=normalized,
                budgets_by_campaign=budgets,
                spend_ratio=float(settings.INTRADAY_BLEED_SPEND_RATIO),
                ctr_threshold=float(settings.INTRADAY_BLEED_CTR_THRESHOLD),
            )
            if not alerts:
                return stats

            window_start = datetime.now(timezone.utc) - timedelta(
                hours=int(settings.INTRADAY_SUPPRESSION_HOURS)
            )
            already = await _recently_alerted_campaigns(session, full_tenant.id, window_start)
            language = full_tenant.preferred_language or "roman_urdu"

            wa_client = WhatsAppClient(access_token=wa_token)
            try:
                for alert in alerts:
                    cid = str(alert.get("campaign_id", ""))
                    if cid in already:
                        stats["skipped_suppressed"] += 1
                        logger.info(f"🔇 Suppressed duplicate pacing alert for campaign {cid}")
                        continue
                    message = format_pacing_alert(alert, language=language)
                    try:
                        token_pause = generate_action_token(
                            tenant_id=str(full_tenant.id),
                            campaign_id=cid,
                            action="PAUSE",
                        )
                        token_dismiss = generate_action_token(
                            tenant_id=str(full_tenant.id),
                            campaign_id=cid,
                            action="DISMISS",
                        )
                        header_txt = "🚨 Intraday Bleed Alert" if language == "english" else "🚨 Pacing Bleed Alert"
                        btn_pause_lbl = "🔴 Pause Ad" if language == "english" else "🔴 Pause Karein"
                        btn_dismiss_lbl = "Keep Running" if language == "english" else "Chalta Rehne Dein"

                        try:
                            await wa_client.send_interactive_buttons(
                                recipient_number=full_tenant.whatsapp_notification_number,
                                header_text=header_txt,
                                body_text=message,
                                button_approve_id=token_pause,
                                button_reject_id=token_dismiss,
                                button_approve_label=btn_pause_lbl,
                                button_reject_label=btn_dismiss_lbl,
                            )
                        except Exception as send_err:
                            logger.warning(f"Interactive button send failed, falling back to text: {send_err}")
                            await wa_client.send_text_message(
                                recipient_number=full_tenant.whatsapp_notification_number,
                                message_text=message,
                            )
                        session.add(AuditLog(
                            tenant_id=full_tenant.id,
                            action_type="INTRADAY_PACING_ALERT",
                            action_details={
                                "campaign_id": cid,
                                "campaign_name": alert.get("campaign_name"),
                                **alert.get("details", {}),
                            },
                            executed_by="AGENTZLINE_PACING",
                            executed_by_whatsapp_num=full_tenant.whatsapp_notification_number,
                        ))
                        await session.commit()
                        already.add(cid)
                        stats["alerts"] += 1
                        logger.warning(f"🚨 Pacing alert sent: {alert.get('campaign_name')} ({cid})")
                    except Exception as exc:
                        await session.rollback()
                        stats["errors"] += 1
                        logger.error(f"Failed to send pacing alert for {cid}: {exc}")
            finally:
                await wa_client.close()
    return stats


async def run_intraday_pacing_job() -> dict[str, int]:
    """
    Phase-2: Intraday pacing sweep (2 PM & 6 PM PKT).

    Fetches today's partial Meta insights per tenant, runs the deterministic
    bleed detector, suppresses duplicates within INTRADAY_SUPPRESSION_HOURS,
    and delivers bilingual urgent WhatsApp alerts.
    """
    logger.info("⏱️ Intraday pacing job triggered")
    settings = get_settings()
    is_test_env = (
        settings.APP_ENV == "test"
        or "sqlite" in settings.DATABASE_URL
        or "test" in settings.DATABASE_URL
    )
    max_jitter = 0.05 if is_test_env else float(settings.SCHEDULER_JITTER_MAX_SECONDS)
    totals = {"alerts": 0, "skipped_suppressed": 0, "errors": 0, "tenants": 0}

    async with async_session_maker() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()
        if not tenants:
            return totals
        totals["tenants"] = len(tenants)
        semaphore = asyncio.Semaphore(5)
        # Detach ids only; each worker re-loads its tenant in its own session
        tenant_ids = [t.id for t in tenants]

    async def _run_one(tid: Any) -> dict[str, int]:
        return await _process_tenant_pacing(tid, semaphore, max_jitter, is_test_env, settings)

    results = await asyncio.gather(*(_run_one(tid) for tid in tenant_ids))
    for r in results:
        for k in ("alerts", "skipped_suppressed", "errors"):
            totals[k] += r.get(k, 0)
    logger.info(f"⏱️ Pacing sweep done: {totals}")
    return totals


def start_scheduler():
    """
    Configure and start the APScheduler.

    Parses DAILY_REPORT_TIME from settings and registers the job.
    """
    settings = get_settings()

    hour, minute = map(int, settings.DAILY_REPORT_TIME.split(":"))

    scheduler.add_job(
        run_daily_report_job,
        "cron",
        hour=hour,
        minute=minute,
        timezone=settings.REPORT_TIMEZONE,
        id="daily_bronze_report",
        replace_existing=True,
    )

    # Phase-1 Task #2: midnight token-expiry watchdog
    scheduler.add_job(
        run_token_expiry_watchdog,
        "cron",
        hour=0,
        minute=5,
        timezone=settings.REPORT_TIMEZONE,
        id="token_expiry_watchdog",
        replace_existing=True,
    )

    # Phase-2: intraday pacing sweeps (2 PM & 6 PM PKT)
    for job_id, (p_hour, p_minute) in {
        "intraday_pacing_14": (14, 0),
        "intraday_pacing_18": (18, 0),
    }.items():
        scheduler.add_job(
            run_intraday_pacing_job,
            "cron",
            hour=p_hour,
            minute=p_minute,
            timezone=settings.REPORT_TIMEZONE,
            id=job_id,
            replace_existing=True,
        )

    scheduler.start()
    logger.info(
        f"📅 Scheduler started — daily report at {settings.DAILY_REPORT_TIME} "
        f"({settings.REPORT_TIMEZONE}), watchdog at 00:05, pacing at 14:00 & 18:00"
    )


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("📅 Scheduler stopped")
