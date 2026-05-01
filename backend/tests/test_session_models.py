from app.models import SessionInstructor, WorkshopParticipant, WorkshopSession


def test_session_models_expose_core_fields() -> None:
    session_schema = WorkshopSession.model_json_schema()
    participant_schema = WorkshopParticipant.model_json_schema()
    instructor_schema = SessionInstructor.model_json_schema()

    assert session_schema["properties"]["status"]["default"] == "scheduled"
    assert session_schema["properties"]["part_generation"]["default"] == 1
    assert "invited_at" in participant_schema["properties"]
    assert "user_id" in instructor_schema["properties"]
