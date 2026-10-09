from clipatlas.director.analyzer import DIRECTOR_PROMPT_VERSION, DirectorAnalyzer


def test_director_prompt_uses_shared_visual_schema_and_chinese_semantics():
    analyzer = DirectorAnalyzer(
        api_key="fixture",
        base_url="https://example.test/v1",
    )

    body = analyzer._request_body("泰钽700在贵州盘山路向上爬坡。")
    system = body["messages"][0]["content"]

    assert DIRECTOR_PROMPT_VERSION == "director-v6-shared-visual-schema"
    assert "subject, action, scene, environment" in system
    assert "anchor_phrase" in system
    assert "Simplified Chinese" in system
    assert "Prefer one continuous shot for one complete sentence" in system
