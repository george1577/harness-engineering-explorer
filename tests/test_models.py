from harness_lab.models import ScriptedModel, find_api_key, message


def test_scripted_model_repeats_last_reply_and_summarizes_without_tools():
    m = ScriptedModel([message("a"), message("b")], summary="S")
    assert [m([], tools=[{}]).content for _ in range(3)] == ["a", "b", "b"]
    assert m([]).content == "S"


def test_find_api_key_env_then_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert find_api_key(tmp_path) == (None, "")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-file\n")
    assert find_api_key(tmp_path) == ("sk-file", ".env file")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert find_api_key(tmp_path) == ("sk-env", "environment variable")
