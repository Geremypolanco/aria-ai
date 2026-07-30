import time

from backend import auth


def test_session_round_trips():
    token = auth.sign_session("user123", "ada@example.com")
    data = auth.verify_session(token)
    assert data["user_id"] == "user123"
    assert data["email"] == "ada@example.com"


def test_session_rejects_tampering():
    token = auth.sign_session("user123", "ada@example.com")
    b, sig = token.split(".", 1)
    tampered = f"{b}x.{sig}"
    assert auth.verify_session(tampered) is None


def test_session_rejects_expired_token(monkeypatch):
    token = auth.sign_session("user123", "ada@example.com")
    future = time.time() + auth.SESSION_MAX_AGE + 3600
    monkeypatch.setattr(time, "time", lambda: future)
    assert auth.verify_session(token) is None


def test_pending_round_trips():
    token = auth.sign_pending("ada@example.com", "Ada", "https://pic")
    data = auth.verify_pending(token)
    assert data["email"] == "ada@example.com"
    assert data["name"] == "Ada"


def test_pending_expires_faster_than_session(monkeypatch):
    token = auth.sign_pending("ada@example.com", "Ada", "")
    future = time.time() + auth.PENDING_MAX_AGE + 60
    monkeypatch.setattr(time, "time", lambda: future)
    assert auth.verify_pending(token) is None


def test_oauth_state_round_trips_and_binds_to_cookie():
    state = auth.make_state()
    assert auth.check_state(state, cookie_state=state) is True
    assert auth.check_state(state, cookie_state="different") is False
    assert auth.check_state(None, cookie_state=state) is False


def test_oauth_state_rejects_expired(monkeypatch):
    state = auth.make_state()
    future = time.time() + auth.STATE_MAX_AGE + 60
    monkeypatch.setattr(time, "time", lambda: future)
    assert auth.check_state(state, cookie_state=state) is False


def test_verify_session_rejects_garbage():
    assert auth.verify_session(None) is None
    assert auth.verify_session("not-a-token") is None
    assert auth.verify_session("no-dot-here") is None
