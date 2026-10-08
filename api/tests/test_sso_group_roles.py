"""Roles from groups: SSO sign-in sets a person's role from their groups.

What has to be true: off does nothing; the highest role any group gives wins;
groups come from the token or, failing that, from directory sync's stored
groups; nothing matching leaves the role alone; the last admin is never
demoted; each change is audited; and a sign-in end to end applies it.
"""

import pytest
from sqlalchemy import select

from app import crypto, oidc, sso_roles
from app.models import AuditLog, DirectoryPerson, OauthClient, SsoConfig

RULES = [
    {"group": "Sales", "role": "agent"},
    {"group": "Sales Managers", "role": "manager"},
    {"group": "GoalGetter Admins", "role": "admin"},
]


@pytest.fixture
def config(db, org):
    row = SsoConfig(
        organization_id=org.id, enabled=True, provider="microsoft",
        role_sync=True, role_rules=RULES,
    )
    db.add(row)
    db.flush()
    return row


def test_off_does_nothing(db, org, config, make_user):
    config.role_sync = False
    peter = make_user("agent", name="Peter Parker")

    assert sso_roles.apply(db, config, peter, {"groups": ["Sales Managers"]}, peter.email) is None
    assert peter.org_role == "agent"


def test_the_highest_role_any_group_gives_wins(db, org, config, make_user):
    peter = make_user("agent", name="Peter Parker")

    changed = sso_roles.apply(db, config, peter, {"groups": ["sales", "SALES MANAGERS"]}, peter.email)

    assert changed == "manager"
    assert peter.org_role == "manager"


def test_app_roles_count_too(db, org, config, make_user):
    peter = make_user("agent", name="Peter Parker")

    sso_roles.apply(db, config, peter, {"roles": ["GoalGetter Admins"]}, peter.email)

    assert peter.org_role == "admin"


def test_directory_groups_are_used_when_the_token_has_none(db, org, config, make_user):
    """Entra with directory sync on needs no token configuration at all."""
    diana = make_user("agent", name="Diana Prince")
    db.add(DirectoryPerson(
        organization_id=org.id, provider="microsoft", external_id="oid-diana",
        email=diana.email, display_name=diana.full_name, groups=["Sales Managers"],
        status="approved", user_account_id=diana.id,
    ))
    db.flush()

    sso_roles.apply(db, config, diana, {"oid": "oid-diana"}, diana.email)

    assert diana.org_role == "manager"


def test_nothing_matching_leaves_the_role_alone(db, org, config, make_user):
    """A rule set that forgot a group must not quietly demote everybody in it."""
    clark = make_user("manager", name="Clark Kent")

    assert sso_roles.apply(db, config, clark, {"groups": ["Marketing"]}, clark.email) is None
    assert clark.org_role == "manager"


def test_a_group_can_demote(db, org, config, make_user):
    make_user("admin", name="Other Admin")
    bruce = make_user("admin", name="Bruce Wayne")

    sso_roles.apply(db, config, bruce, {"groups": ["Sales"]}, bruce.email)

    assert bruce.org_role == "agent"


def test_the_last_admin_is_never_demoted(db, org, config, make_user):
    bruce = make_user("admin", name="Bruce Wayne")

    assert sso_roles.apply(db, config, bruce, {"groups": ["Sales"]}, bruce.email) is None
    assert bruce.org_role == "admin"


def test_a_change_is_audited(db, org, config, make_user):
    peter = make_user("agent", name="Peter Parker")

    sso_roles.apply(db, config, peter, {"groups": ["Sales Managers"]}, peter.email)

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "user.role_changed"))
    assert entry is not None


@pytest.mark.parametrize(
    "rules, words",
    [
        ([{"group": "", "role": "agent"}], "needs a group"),
        ([{"group": "Sales", "role": "wizard"}], "not a role"),
        ([{"group": "Sales", "role": "agent"}, {"group": "sales", "role": "admin"}], "two rules"),
    ],
)
def test_bad_rules_are_refused_in_words(rules, words):
    with pytest.raises(ValueError, match=words):
        sso_roles.check_rules(rules)


# ── The settings API ────────────────────────────────────────────────────────


def settings(**extra):
    return {"enabled": False, "provider": "microsoft", "scopes": "openid profile email",
            "button_label": "Sign in", "auto_provision": False, "require_sso": False, **extra}


def test_rules_are_saved_and_read_back(client, sign_in, db, org, make_user):
    sign_in(make_user("admin"))

    saved = client.put("/api/admin/sso", json=settings(role_sync=True, role_rules=RULES)).json()

    assert saved["role_sync"] is True
    assert [r["group"] for r in saved["role_rules"]] == ["Sales", "Sales Managers", "GoalGetter Admins"]


def test_switching_on_with_no_rules_is_refused(client, sign_in, make_user):
    sign_in(make_user("admin"))

    reply = client.put("/api/admin/sso", json=settings(role_sync=True, role_rules=[]))

    assert reply.status_code == 400


def test_an_older_screen_saving_does_not_wipe_the_rules(client, sign_in, db, org, config, make_user):
    sign_in(make_user("admin"))

    client.put("/api/admin/sso", json=settings())

    db.refresh(config)
    assert config.role_rules == RULES and config.role_sync is True


# ── A sign-in, end to end ───────────────────────────────────────────────────


def test_signing_in_applies_the_groups(client, db, org, config, make_user, monkeypatch):
    make_user("admin", name="Bruce Wayne")
    peter = make_user("agent", name="Peter Parker")
    db.add(OauthClient(
        organization_id=org.id, provider="microsoft", client_id="client",
        client_secret_encrypted=crypto.encrypt("s"), tenant_id="contoso",
    ))
    db.flush()
    flow = oidc.new_flow_state()
    monkeypatch.setattr(oidc, "discover", lambda issuer: {"token_endpoint": "x", "jwks_uri": "y"})
    monkeypatch.setattr(oidc, "exchange_code", lambda document, **kw: {"id_token": "token"})
    monkeypatch.setattr(
        oidc, "verify_id_token",
        lambda document, token, **kw: {"sub": "sub-peter", "email": peter.email, "groups": ["Sales Managers"]},
    )
    client.cookies.set("gg_sso_flow", oidc.seal_flow(flow, "/"))

    reply = client.get(
        f"/api/auth/sso/callback?state={flow.state}&code=abc", follow_redirects=False
    )

    assert reply.status_code == 303, reply.text
    db.refresh(peter)
    assert peter.org_role == "manager"
