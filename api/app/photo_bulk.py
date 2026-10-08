"""Four hundred headshots in one go.

**Because the alternative is four hundred visits to four hundred profiles.** A
company that has photographs of its staff has them in a folder, named after the
person, and the job is to get them in — not to make somebody click through the
roster for an afternoon.

**Matched by the filename, through the same ladder that matches a CRM row.**
`pparker.jpg` finds Peter Parker the same way `pparker@` in a Snowflake view does:
exact email, then the login forms derived from a name, then a refusal where two
people fit. Writing a second, worse matcher for filenames would mean two places
to fix the day somebody's surname has an apostrophe in it.

**Every file gets a line in the report, including the ones that worked.** A bulk
action that says "312 updated" and nothing else leaves the other eighty-eight to
be found by noticing they are missing.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import identity, images, photos
from app.models import UserAccount

__all__ = ["MAX_ARCHIVE_BYTES", "Outcome", "Report", "apply_archive", "place"]

#: The largest archive accepted.
#:
#: Four hundred photographs at the ten megabytes each an individual upload allows
#: would be four gigabytes, which is not a thing to hold in memory. A hundred
#: megabytes is roughly four hundred phone photographs and comfortably more than
#: four hundred headshots.
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024

#: What a file has to be named to be considered at all.
SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class Outcome:
    """One file, and what became of it."""

    filename: str
    #: `matched`, `unmatched`, `ambiguous`, or `rejected`.
    status: str
    detail: str
    user_id: int | None = None
    user_name: str | None = None


@dataclass
class Report:
    outcomes: list[Outcome]

    @property
    def matched(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "matched")

    @property
    def unresolved(self) -> int:
        return sum(1 for o in self.outcomes if o.status != "matched")


def apply_archive(db: DbSession, org_id: int, raw: bytes) -> Report:
    """Read a zip of photographs and attach each to whoever it names.

    Subfolders are ignored rather than refused — a folder exported from a phone
    or a shared drive arrives with them, and the name at the end is the part that
    matters.
    """
    outcomes: list[Outcome] = []

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return Report(
            [Outcome("", "rejected", "That file is not a zip archive.")]
        )

    for info in archive.infolist():
        if info.is_dir():
            continue

        name = info.filename.rsplit("/", 1)[-1]
        # Skip what a Mac puts in every archive, rather than reporting it as an
        # unmatched person.
        if not name or name.startswith(".") or "__MACOSX" in info.filename:
            continue
        try:
            with archive.open(info) as handle:
                data = handle.read(MAX_ARCHIVE_BYTES + 1)
        except Exception:  # noqa: BLE001 — one bad entry must not end the run
            outcomes.append(Outcome(name, "rejected", "That file could not be read."))
            continue
        outcomes.append(place(db, org_id, name, data))

    return Report(outcomes)


def place(db: DbSession, org_id: int, filename: str, data: bytes) -> Outcome:
    """One photograph: whose it is, by its name, and set on them.

    **Shared by the zip and by single photos**, so a file dropped on its own is
    matched exactly as the same file inside an archive would be. The name is
    the file's own, without any folder before it or extension after.
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not name.lower().endswith(SUFFIXES):
        return Outcome(name, "rejected", "Not a .jpg, .png or .webp.")
    stem = name.rsplit(".", 1)[0]
    user, why = _who(db, org_id, stem)
    if user is None:
        return Outcome(name, why or "unmatched", _explain(why, stem))
    try:
        photos.set_custom(db, user, data)
    except images.ImageProblem as problem:
        return Outcome(name, "rejected", str(problem))
    except Exception:  # noqa: BLE001 — a bad file is a line in the report, not a 500
        return Outcome(name, "rejected", "That file could not be read.")
    return Outcome(name, "matched", "Photo set.", user.id, user.full_name)


def _who(db: DbSession, org_id: int, stem: str) -> tuple[UserAccount | None, str]:
    """The one person this filename names, or why not.

    Exact email first — a file may be called `peter.parker@acme.com.jpg` — then
    the username ladder, which is where `pparker.jpg` is resolved.
    """
    exact = db.scalar(
        select(UserAccount).where(
            UserAccount.organization_id == org_id,
            UserAccount.hidden_at.is_(None),
            UserAccount.email.ilike(stem),
        )
    )
    if exact is not None:
        return exact, "matched"

    user_id = identity._by_username(db, org_id, stem)
    if user_id is not None:
        return db.get(UserAccount, user_id), "matched"

    # Distinguish "nobody" from "more than one", because they need different
    # fixes: add the person, or rename the file to their address.
    forms = identity._roster(db, org_id).get(identity._norm(stem))
    if forms and len(forms) > 1:
        return None, "ambiguous"
    return None, "unmatched"


def _explain(status: str, stem: str) -> str:
    if status == "ambiguous":
        return (
            f"More than one person could be “{stem}”. Rename the file to their "
            "email address."
        )
    return f"Nobody here matches “{stem}”."
