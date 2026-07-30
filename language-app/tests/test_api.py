from fastapi.testclient import TestClient

from backend.main import app


def test_full_onboarding_lesson_and_progress_flow():
    with TestClient(app) as client:
        create_res = client.post(
            "/api/users",
            json={
                "display_name": "Ada",
                "native_lang": "English",
                "target_lang": "Spanish",
                "level": "A1",
                "interests": ["music"],
            },
        )
        assert create_res.status_code == 200
        user = create_res.json()
        user_id = user["id"]
        assert user["hearts"] == 5
        assert user["xp"] == 0

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
        user = client.post(
            "/api/users",
            json={"display_name": "Ada", "native_lang": "English", "target_lang": "Spanish", "level": "A1"},
        ).json()
        locked_unit_id = "C2-0"
        res = client.get(f"/api/lessons/{user['id']}/unit/{locked_unit_id}")
        assert res.status_code == 403


def test_unknown_user_returns_404():
    with TestClient(app) as client:
        res = client.get("/api/users/does-not-exist")
        assert res.status_code == 404


def test_health_endpoint():
    with TestClient(app) as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        assert "hf_configured" in res.json()
