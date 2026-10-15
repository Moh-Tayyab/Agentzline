"""add auth nonce and unique constraints

Revision ID: 9f1a2b3c4d5e
Revises: 823c42be6d8c
Create Date: 2026-10-15

Adds:
- tenants.api_key_hash (String(64), nullable, unique index)
- agent_action_audit_logs.token_nonce (String(64), nullable, unique index)
- uq_tenant_external_order on orders(tenant_id, external_order_id)
- uq_account_campaign_date on campaign_metrics_snapshots(ad_account_id, external_campaign_id, snapshot_date)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f1a2b3c4d5e"
down_revision: Union[str, None] = "823c42be6d8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("api_key_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_tenants_api_key_hash"), "tenants", ["api_key_hash"], unique=True)

    op.add_column(
        "agent_action_audit_logs",
        sa.Column("token_nonce", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_agent_action_audit_logs_token_nonce"),
        "agent_action_audit_logs",
        ["token_nonce"],
        unique=True,
    )

    op.create_unique_constraint(
        "uq_tenant_external_order", "orders", ["tenant_id", "external_order_id"]
    )
    op.create_unique_constraint(
        "uq_account_campaign_date",
        "campaign_metrics_snapshots",
        ["ad_account_id", "external_campaign_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_account_campaign_date", "campaign_metrics_snapshots", type_="unique")
    op.drop_constraint("uq_tenant_external_order", "orders", type_="unique")
    op.drop_index(
        op.f("ix_agent_action_audit_logs_token_nonce"),
        table_name="agent_action_audit_logs",
    )
    op.drop_column("agent_action_audit_logs", "token_nonce")
    op.drop_index(op.f("ix_tenants_api_key_hash"), table_name="tenants")
    op.drop_column("tenants", "api_key_hash")
