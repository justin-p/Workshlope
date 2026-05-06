from app.models import Lesson, LessonPart, LessonRepo


def test_lesson_models_expose_manifest_sync_fields() -> None:
    repo_schema = LessonRepo.model_json_schema()
    lesson_schema = Lesson.model_json_schema()
    part_schema = LessonPart.model_json_schema()

    assert repo_schema["properties"]["full_name"]["maxLength"] == 255
    assert lesson_schema["properties"]["slug"]["maxLength"] == 255
    assert part_schema["properties"]["slug"]["maxLength"] == 255
