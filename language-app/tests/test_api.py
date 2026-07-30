from fastapi.testclient import TestClient

from backend.main import app
from conftest import dev_login


def _onboard(client, email="ada@example.com"):
    dev_login(client, email)
    res = client.post(
        "/api/users",
        json={
            "display_name": "Ada",
            "native_lang": "English",
            "target_lang": "Spanish",
            "level": "A1",
            "interests": ["music"],
        },
    )
    assert res.status_code == 200
    return res.json()


def test_full_onboarding_lesson_and_progress_flow():
    with TestClient(app) as client:
        user = _onboard(client)
        user_id = user["id"]
        assert user["hearts"] == 5
        assert user["xp"] == 0
        assert "email" not in user  # not part of the public UserProfile model

        path_res = client.get(f"/api/lessons/{user_id}/path")
        assert path_res.status_code == 200
        units = path_res.json()
        a1_units = [u for u in units if u["level"] == "A1"]
        assert all(u["state"] == "available" for u in a1_units)
        locked_units = [u for u in units if u["level"] != "A1"]
        assert all(u["state"] == "locked" for u in locked_units)

        first_unit_id = a1_units[0]["id"]
        lesson_res = client.get(f"/api/lessons/{user_id}/unit/{first_unit_id}")
        assert lesson_res.status_code == 200
        exercises = lesson_res.json()
        assert len(exercises) > 0
        assert exercises[0]["vocab_key"]

        for ex in exercises:
            answer_res = client.post(
                f"/api/lessons/{user_id}/answer",
                json={"vocab_key": ex["vocab_key"], "correct": True, "attempts_before_correct": 0},
            )
            assert answer_res.status_code == 200

        complete_res = client.post(
            f"/api/lessons/{user_id}/complete",
            json={"unit_id": first_unit_id, "score": 1.0},
        )
        assert complete_res.status_code == 200
        complete = complete_res.json()
        assert complete["xp_gained"] == 30
        assert complete["mastered"] is True

        progress_res = client.get(f"/api/progress/{user_id}")
        assert progress_res.status_code == 200
        progress = progress_res.json()
        assert progress["xp"] == 30
        assert progress["units_mastered"] == 1


def test_locked_unit_returns_403():
    with TestClient(app) as client:
        user = _onboard(client)
        locked_unit_id = "C2-0"
        res = client.get(f"/api/lessons/{user['id']}/unit/{locked_unit_id}")
        assert res.status_code == 403


def test_no_session_returns_401():
    with TestClient(app) as client:
        res = client.get("/api/users/does-not-exist")
        assert res.status_code == 401


def test_accessing_someone_elses_profile_returns_403():
    with TestClient(app) as client:
        user = _onboard(client)
        res = client.get(f"/api/users/{user['id']}not-mine")
        assert res.status_code == 403


def test_returning_user_reuses_profile_via_dev_login():
    with TestClient(app) as client:
        first = _onboard(client, email="returning@example.com")
        client.post("/auth/logout")
        second_res = client.get("/api/session")
        assert second_res.json()["authenticated"] is False

        dev_login(client, "returning@example.com")
        session_res = client.get("/api/session")
        session = session_res.json()
        assert session["authenticated"] is True
        assert session["user_id"] == first["id"]


def test_creating_profile_without_login_is_rejected():
    with TestClient(app) as client:
        res = client.post(
            "/api/users",
            json={"display_name": "Ghost", "native_lang": "English", "target_lang": "Spanish", "level": "A1"},
        )
        assert res.status_code == 401


def test_health_endpoint():
    with TestClient(app) as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert "hf_configured" in body
        assert "google_configured" in body
