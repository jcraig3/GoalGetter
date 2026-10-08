"""One office, and one metric in use, per name — ignoring case.

Two offices called "Gotham" (QA-7) and two metrics called "Closed Deals"
(QA-9) made every picker that lists them ambiguous. Archived ones are left
out, so an old name can be reused by something new.

**Refuses to run over a clash rather than picking a winner.** Renaming or
archiving somebody's office is not a migration's decision; the error names
every clash so they can be sorted out on the Offices and Metrics pages first.

Revision ID: c5e1a8f3d720
Revises: b2f8c4d1e937
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e1a8f3d720"
down_revision: str | None = "b2f8c4d1e937"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = {
    "office": "uq_office_org_name_lower",
    "metric_definition": "uq_metric_definition_org_name_lower",
}


def upgrade() -> None:
    connection = op.get_bind()
    clashes = []
    for table in TABLES:
        rows = connection.execute(
            sa.text(
                f"""
                SELECT organization_id, min(name) AS name, count(*) AS n
                FROM {table}
                WHERE archived_at IS NULL
                GROUP BY organization_id, lower(name)
                HAVING count(*) > 1
                """
            )
        ).all()
        clashes += [f"{table} '{r.name}' ×{r.n} (organization {r.organization_id})" for r in rows]
    if clashes:
        raise RuntimeError(
            "Rename or archive these before upgrading — each name has to be "
            "unique among those in use: " + "; ".join(clashes)
        )

    for table, index in TABLES.items():
        op.create_index(
            index,
            table,
            ["organization_id", sa.text("lower(name)")],
            unique=True,
            postgresql_where=sa.text("archived_at IS NULL"),
        )


def downgrade() -> None:
    for table, index in TABLES.items():
        op.drop_index(index, table_name=table)
