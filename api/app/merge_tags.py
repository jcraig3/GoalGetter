"""What an admin may write into a celebration, and how it is filled in.

**The air-gapped answer to "make it feel less repetitive".** The product this
borrows from reaches for a language model to reword an announcement each time.
That needs an outbound connection, a per-win latency budget, and a willingness
to put text nobody wrote on a wall in front of the floor. Writing three lines
and picking one at random does the same job, costs nothing, and the words are
always the ones somebody chose.

**Four tags, not an expression language.** Every one of them always has a
value, which is what keeps a message from rendering with a hole in the middle
of it — `{team}` is an obvious fifth until somebody on no team wins something
and the wall says "Peter Parker on  closed a big one". The same reasoning that
kept `AchievementRule.comparator` to two operators.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

__all__ = ["TAGS", "MergeTagError", "pick", "render", "variants", "check"]


@dataclass(frozen=True)
class Tag:
    name: str
    #: What it stands for, shown beside the button that inserts it.
    describes: str
    #: What it looks like filled in, for the picker and the preview.
    example: str


TAGS: tuple[Tag, ...] = (
    Tag("name", "Who did it", "Peter Parker"),
    Tag("first_name", "Just their first name", "Peter"),
    Tag("value", "The figure, formatted", "$6,200"),
    Tag("metric", "What was measured", "Revenue"),
)

#: `{name}`, and nothing cleverer. No filters, no expressions, no nesting: a
#: template language on a wall is a thing to debug in front of an office.
PATTERN = re.compile(r"\{([a-z_]+)\}")

#: How many alternatives one message may hold.
#:
#: Enough that a floor hearing four wins a day does not hear the same sentence
#: twice; few enough that the box stays a box rather than a document.
MAX_VARIANTS = 10

#: The longest one line may be. A celebration is read from across a room.
MAX_LENGTH = 200


class MergeTagError(ValueError):
    """A message somebody wrote that cannot be filled in."""


def variants(message: str) -> list[str]:
    """The alternatives in a message, one per line.

    **One per line rather than a separator character**, because a separator is
    a thing to explain and to escape, and because a text box with three lines
    in it already looks like three alternatives.
    """
    return [line.strip() for line in (message or "").splitlines() if line.strip()]


def check(message: str) -> None:
    """Refuse a message that would render wrong, with a sentence to act on.

    **At the moment it is written, not when it fires.** A typo'd tag that is
    only caught on a wall is caught by whoever is standing in front of it,
    hours later, with no way to tell what was meant.
    """
    lines = variants(message)
    if not lines:
        return

    if len(lines) > MAX_VARIANTS:
        raise MergeTagError(
            f"That is {len(lines)} alternatives. The most is {MAX_VARIANTS} — "
            "past that nobody can remember what the wall might say."
        )

    for line in lines:
        if len(line) > MAX_LENGTH:
            raise MergeTagError(
                f"One line is {len(line)} characters. The longest that reads "
                f"across a room is {MAX_LENGTH}."
            )

    known = {tag.name for tag in TAGS}
    unknown = sorted(
        {name for line in lines for name in PATTERN.findall(line)} - known
    )
    if unknown:
        offered = ", ".join(f"{{{tag.name}}}" for tag in TAGS)
        named = ", ".join(f"{{{name}}}" for name in unknown)
        raise MergeTagError(
            f"{named} is not something that can be filled in. Available: {offered}."
        )


def pick(message: str, seed: int) -> str:
    """One alternative, chosen by the win rather than by a coin.

    **Seeded, not random.** The same win always produces the same sentence,
    which means a wall re-reading its feed does not quietly reword an
    announcement somebody already read, and a test can assert what it says
    without reaching into a random number generator. Across wins the choice is
    unpredictable, which is the only place unpredictability was wanted.
    """
    lines = variants(message)
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]

    # A hash rather than `seed % len`: consecutive fact ids would otherwise
    # cycle through the alternatives in order, which reads as a rota rather
    # than as variety.
    digest = hashlib.sha256(str(seed).encode()).digest()
    return lines[int.from_bytes(digest[:4], "big") % len(lines)]


def render(message: str, seed: int, **values: str) -> str:
    """One alternative with its tags filled in.

    An unknown tag is left as it was written rather than blanked. `check`
    refuses those on the way in, so reaching here means an older row from
    before a tag was renamed — and showing `{squad}` on a wall is at least
    something an admin can search for.
    """
    chosen = pick(message, seed)
    if not chosen:
        return ""
    return PATTERN.sub(
        lambda match: values.get(match.group(1), match.group(0)), chosen
    )
