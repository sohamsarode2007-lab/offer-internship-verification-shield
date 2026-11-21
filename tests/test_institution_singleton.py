"""get_institution is get-or-create under a unique name; a lost race returns the winner's row."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.models import Institution
from app.services import institution_dashboard as dash


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_repeated_calls_return_one_row():
    db = _db()
    a, b = dash.get_institution(db), dash.get_institution(db)
    assert a.id == b.id and db.query(Institution).count() == 1


def test_a_lost_race_returns_the_existing_row(monkeypatch):
    db = _db()
    original = db.query
    state = {"hidden": True}

    class Hidden:
        def order_by(self, *a): return self
        def first(self): return None

    def fake_query(model, *a, **k):
        if model is Institution and state["hidden"]:
            state["hidden"] = False  # the first read misses; a rival row already exists
            return Hidden()
        return original(model, *a, **k)

    db.add(Institution(name=dash.INSTITUTION_NAME)); db.commit()
    monkeypatch.setattr(db, "query", fake_query)
    got = dash.get_institution(db)
    assert got.name == dash.INSTITUTION_NAME and original(Institution).count() == 1
