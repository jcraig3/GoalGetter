"""The catalogue of things worth telling somebody about.

Kept small on purpose. A bell only works if it is rare: every event that fires
predictably teaches people to stop looking, and it takes the useful ones with
it. Five that always mean something beat eight where three are wallpaper.

Seven, and three of them are competitions — which needs justifying against the
paragraph above. A competition fires each of its events **once, for one contest**:
you are told it started, and later where you finished. Somebody in four contests a
year hears eight things. That is the opposite of wallpaper, and unlike a goal
these have a deadline attached, which is the whole reason they are worth an
interruption.

Two events were cut before any of this was built:

    goal.threshold      Being halfway to a monthly target on the 15th is what
                        is supposed to happen. The pace marker already says it
                        on screen, more precisely, without interrupting anyone.

    goal.at_risk        Merged into `goal.period_ending`, which said the same
                        thing days apart. It was also a latching event
                        describing an oscillating condition: firing the first
                        time somebody dipped behind spent the single shot, and
                        they would hear nothing on the 25th when it mattered.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventType:
    key: str
    #: May this appear on a wall screen?
    #:
    #: A screen has no session and no viewer — it is read by whoever walks
    #: past. Achievement is celebrated in public; falling behind is a
    #: conversation with your manager, and putting it on a permanent display in
    #: front of the floor is public shaming.
    #:
    #: A property of the event type, deliberately: not a per-notification flag
    #: and not an admin setting. A checkbox somebody could tick is a checkbox
    #: somebody will tick.
    public: bool
    #: Worth interrupting the recipient with an overlay, rather than waiting to
    #: be found in the bell. Reserved for things that only happen once.
    celebrate: bool
    #: One of the big ones.
    #:
    #: **The distinction a wall in a quiet room needs.** Winning a contest and
    #: hitting a target are the moments worth stopping a rotation for anywhere;
    #: a shout-out and an achievement rule are worth it on a sales floor and
    #: are noise in a reception area — and an admin can create a rule that
    #: fires forty times a day, which is exactly how a takeover teaches people
    #: to ignore takeovers.
    #:
    #: A property of the type rather than a per-notification flag, for the same
    #: reason as `public`: a checkbox somebody could tick is a checkbox
    #: somebody will tick.
    major: bool = False


GOAL_ACHIEVED = EventType("goal.achieved", public=True, celebrate=True, major=True)
#: A stretch level past the target, crossed. One key per level, so each is
#: announced once per period and none can latch another through the unique
#: index. Major, like the target itself: it is more than the target.
GOAL_STRETCH = tuple(
    EventType(f"goal.stretch.{level}", public=True, celebrate=True, major=True)
    for level in (1, 2, 3)
)
STRETCH_PREFIX = "goal.stretch."
GOAL_ASSIGNED = EventType("goal.assigned", public=False, celebrate=False)
GOAL_PERIOD_ENDING = EventType("goal.period_ending", public=False, celebrate=False)
#: A person wrote this one. Public and celebrated because the entire point of a
#: shout-out is that other people see it.
RECOGNITION = EventType("recognition", public=True, celebrate=True)

#: Somebody commented on a shout-out or an achievement about you, or on one
#: you wrote (6.15). Private: it is a conversation, not news for the wall.
FEED_COMMENT = EventType("feed.comment", public=False, celebrate=False)

#: A contest you are in has begun. Private: the wall gets the standings screen
#: itself, which says more than a line of text would.
COMPETITION_STARTED = EventType("competition.started", public=False, celebrate=False)
#: Won. The highest-value notification in the product — it is the moment a prize
#: is handed over, so it goes on the wall and it interrupts.
COMPETITION_WON = EventType("competition.won", public=True, celebrate=True, major=True)
#: Where everybody else finished. Private, because coming fifth is not a thing
#: to put on a permanent display in front of the floor — the same reasoning that
#: keeps `goal.period_ending` off the wall.
COMPETITION_FINISHED = EventType("competition.finished", public=False, celebrate=False)

#: Somebody's birthday, marked on a working day near it.
#:
#: **Public, and not `major`.** A floor wants to know; a reception screen set
#: to "important only" wants contest wins and nothing else. It is also the one
#: public event nobody earned, which is exactly why it should not outrank the
#: ones people did.
BIRTHDAY = EventType("person.birthday", public=True, celebrate=True)

#: A work anniversary — "three years today".
#:
#: Same reasoning as a birthday, and the same answer.
WORK_ANNIVERSARY = EventType("person.work_anniversary", public=True, celebrate=True)

#: Somebody won something on the prize wheel.
#:
#: **Public, and only for a win.** A miss is never announced: a wall is read by
#: whoever walks past, and "Peter spun and got nothing" is the same kind of
#: thing as "Peter is behind on his goal" — true, and nobody else's business.
#:
#: **Not `major`.** It is luck rather than work, so a screen set to "important
#: only" leaves it out; a floor on "all" watches the wheel land.
WHEEL_WON = EventType("wheel.won", public=True, celebrate=True)

#: A data source has failed repeatedly and has stopped importing.
#:
#: **Private, and never on a wall.** A broken integration is an operational
#: matter for whoever administers the deployment; putting "your CRM is down" on a
#: screen in front of the sales floor tells the wrong forty people. Not
#: celebrated, for reasons that need no explaining.
SOURCE_FAILING = EventType("data_source.failing", public=False, celebrate=False)

CATALOGUE: dict[str, EventType] = {
    event.key: event
    for event in (
        GOAL_ACHIEVED,
        *GOAL_STRETCH,
        GOAL_ASSIGNED,
        GOAL_PERIOD_ENDING,
        RECOGNITION,
        FEED_COMMENT,
        COMPETITION_STARTED,
        COMPETITION_WON,
        COMPETITION_FINISHED,
        BIRTHDAY,
        WORK_ANNIVERSARY,
        WHEEL_WON,
        SOURCE_FAILING,
    )
}

def achievement(event_key: str) -> EventType:
    """An event type for one achievement rule.

    Built rather than looked up, because rules are created by admins at runtime
    and the catalogue is a compile-time thing. Public and celebrated: a rule
    exists precisely to put a win on a wall.

    The key carries the rule id (`achievement:7`), so two rules on the same
    metric are two distinct events and neither can suppress the other through
    the unique index.
    """
    # Not `major`: a rule is whatever an admin wrote, and one that fires on
    # every closed deal is a takeover every few minutes. They belong to the
    # "all" setting, which is a choice somebody made for that room.
    return EventType(event_key, public=True, celebrate=True)


#: What a wall screen and the Achievements page are allowed to show.
#:
#: Derived from the catalogue rather than written out again, so adding a public
#: event cannot leave this list behind — the sort of duplicate that agrees on
#: the day it is written and disagrees six months later.
PUBLIC_EVENT_KEYS = tuple(e.key for e in CATALOGUE.values() if e.public)

#: Achievement-rule events carry the rule id, so their keys cannot be in the
#: fixed list above — an admin creating a rule cannot wait for a deploy.
ACHIEVEMENT_PREFIX = "achievement:"


def type_for(event_key: str) -> EventType | None:
    """The event type for any key, fixed or runtime.

    One lookup for both kinds, so nothing has to know which it is holding.
    """
    known = CATALOGUE.get(event_key)
    if known is not None:
        return known
    if event_key.startswith(ACHIEVEMENT_PREFIX):
        return achievement(event_key)
    return None


def is_public(event_key: str) -> bool:
    """May this appear on a wall screen and the achievements feed?

    **The single source of truth**, and it exists because there were briefly
    two. The feed matched achievement keys by prefix while `achievement()`
    separately declared them public — so flipping that flag to False changed
    nothing, and a mutation proved it. A field nothing reads is worse than no
    field: it looks like the control and is not.
    """
    event = type_for(event_key)
    return event is not None and event.public

#: How far into a period before "you are not going to make it at this rate" is
#: worth saying. Early enough to act on, late enough that it is not noise —
#: three quarters through, with the target still unmet.
PERIOD_ENDING_ELAPSED = 75.0

#: A backstop, not a rate limit. Every event here fires once per subject per
#: period, so the volume is bounded by how many goals somebody has. This exists
#: so that a misconfigured import which somehow created four hundred goals
#: cannot bury a person's bell.
DAILY_CAP = 30

#: How long a win stays eligible to take over a wall, in seconds.
#:
#: Five minutes. Past that it is not "just happened" any more, and the
#: achievements slide in the rotation is where it belongs instead. This also
#: bounds what a television replays when it reloads: a screen switched on in the
#: morning must not fire yesterday's celebrations one after another.
CELEBRATION_LIFETIME_SECONDS = 300

#: How long a replay stays on offer.
#:
#: Shorter than a real win's window, because a replay is an instruction rather
#: than news: somebody pressed a button meaning "now", and a television that
#: was switched off has not missed a moment worth chasing. Long enough for a
#: wall on a sixty-second poll to pick it up.
REPLAY_WINDOW_SECONDS = 120

#: How long a celebration with no media holds the screen.
#:
#: Long enough to read a name and a number from across a room, short enough that
#: it is not blocking the rotation. One with media runs for the length of its
#: clip instead — capped at `media.MAX_CLIP_SECONDS`, which is why a walk-up is
#: fifteen seconds and not a whole song.
CELEBRATION_HOLD_SECONDS = 10

#: The quiet gap between two takeovers.
#:
#: Without it, four wins arriving in the same minute strobe: the room sees
#: flashing rather than four people being congratulated. The gap is what makes
#: each one land as a separate event.
CELEBRATION_COOLDOWN_SECONDS = 5

#: How long after a win it takes over the screens, so that every screen on the
#: channel starts it at the same moment.
#:
#: **Every television on a channel plays a win at once**, not whenever each one
#: happened to poll — a room with three screens showing the same celebration
#: three seconds apart looks broken rather than celebratory. So the server
#: gives each win a start time and every screen waits for it on a shared clock.
#: The lead has to be longer than the poll interval, or a screen could learn of
#: a win only after it had started everywhere else. Screens poll every three
#: seconds; five leaves room for a slow request.
CELEBRATION_SYNC_LEAD_SECONDS = 5

#: How far back the timetable is worked out from.
#:
#: Twice the window a win is offered for, so that a win ageing out of the offer
#: cannot shift the start of the ones queued behind it — which would let two
#: screens that polled either side of that moment disagree. Only a backlog of
#: celebrations longer than this could still do it, and that is a floor having
#: an extraordinary ten minutes.

#: How long a notification is worth keeping.
#:
#: This table is a feed, not a record: `audit_log` answers "what happened and
#: who did it", and a two-year-old "you hit your August target" answers nothing
#: anybody is asking. Ninety days covers a quarter, which is the longest period
#: a goal can span short of a year.
RETENTION_DAYS = 90


#: How much a wall interrupts itself. One control, three answers.
#:
#: **Not a checkbox per event.** Seven event types is seven checkboxes to reason
#: about, on a page about how a television looks, to express three intentions
#: that actually exist: leave the rotation alone, stop for the big ones, stop
#: for everything.
MILESTONE_LEVELS = ("none", "important", "all")


def interrupts(event_key: str, level: str) -> bool:
    """May this event take over a wall set to `level`?

    Sits beside the catalogue rather than in the renderer, so "which events are
    the big ones" is answered in the file that knows what the events are.
    """
    if level == "none":
        return False

    event = type_for(event_key)
    # `public` and `celebrate` both, and neither implies the other — see the
    # note on `EventType`. An event worth interrupting one person with but not
    # worth putting on a wall would otherwise land on the wall by default.
    if event is None or not (event.public and event.celebrate):
        return False

    return event.major if level == "important" else True
