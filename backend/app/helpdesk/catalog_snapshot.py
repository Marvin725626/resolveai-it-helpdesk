"""Public subset of the immutable service template stored on a submitted ticket."""


def service_snapshot(payload):
    saved = payload.get("service_input") if isinstance(payload, dict) else None
    if not isinstance(saved, dict) or not isinstance(saved.get("fields"), list):
        return None
    answers = saved.get("answers")
    if not isinstance(answers, dict):
        return None
    return {"item_id": saved.get("item_id"), "code": saved.get("code", ""),
        "title": saved.get("title", ""), "version": saved.get("version"),
        "fields": [{"key": field["key"], "label": field.get("label", field["key"]),
            "answer": answers.get(field["key"], "")} for field in saved["fields"]
            if isinstance(field, dict) and isinstance(field.get("key"), str)]}
