"""
AgentZline Report Scheduler.

Schedules the daily Bronze Tier pipeline to run at the configured time
(default: 9:00 AM PKT / Asia/Karachi).
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.core.config import get_settings

scheduler = AsyncIOScheduler()


async def run_daily_report_job():
    """
    Scheduled job: Run the Bronze Tier daily report for all active tenants.

    For each active tenant with registered ad accounts:
    1. Build agent state
    2. Execute LangGraph pipeline
    3. Deliver WhatsApp report
    """
    logger.info("⏰ Daily report job triggered")

    # TODO: Query all active tenants with ad accounts
    # TODO: For each tenant, invoke the Bronze agent graph
    # TODO: Log results to audit trail


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

    scheduler.start()
    logger.info(
        f"📅 Scheduler started — daily report at {settings.DAILY_REPORT_TIME} "
        f"({settings.REPORT_TIMEZONE})"
    )


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("📅 Scheduler stopped")
