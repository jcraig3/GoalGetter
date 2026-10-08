def test_probe_ids(db, org, make_team, make_user):
    e = make_team('Enterprise')
    s = make_team('SMB')
    a = make_user('agent', e, name='Alice')
    b = make_user('agent', e, name='Bob')
    print(f'TEAM ids: enterprise={e.id} smb={s.id}')
    print(f'USER ids: alice={a.id} bob={b.id}')
    from app.models import UserAccount
    print(f'user with id == enterprise.id: {db.get(UserAccount, e.id)}')
