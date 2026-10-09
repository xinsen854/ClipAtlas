from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.projects.store import ProjectStore
from clipatlas.rules.analyzer import RuleAnalysisResult
from clipatlas.rules.models import ProjectRule, RuleKind
from clipatlas.rules.store import ProjectRuleStore


class RecordingRuleAnalyzer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze(self, source_text: str) -> RuleAnalysisResult:
        self.calls.append(source_text)
        return RuleAnalysisResult(
            source_text=source_text,
            rules=[
                ProjectRule(
                    kind=RuleKind.SPEECH_SUPPRESS,
                    match="Official Media",
                ),
                ProjectRule(
                    kind=RuleKind.PRONUNCIATION,
                    match="Model 700",
                    replacement="Model seven hundred",
                ),
            ],
        )


def _client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.project_store = ProjectStore(tmp_path / "projects.sqlite3")
    app.state.project_rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    return TestClient(app)


def _create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Batch Rules Test"})
    assert response.status_code == 201
    return response.json()["id"]


def test_project_rule_draft_list_activate_and_get_active(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)
    rules = [
        {
            "kind": "pronunciation",
            "match": "Model 700",
            "replacement": "Model seven hundred",
        },
        {
            "kind": "semantic_hint",
            "hint": "prefer authoritative public-event footage",
        },
    ]

    created = client.post(
        f"/api/v1/projects/{project_id}/rules/drafts",
        json={"rules": rules},
    )
    assert created.status_code == 201
    assert created.json()["revision"] == 1
    assert created.json()["status"] == "draft"
    assert created.json()["rules"] == [
        {**rules[0], "hint": None, "enabled": True},
        {**rules[1], "match": None, "replacement": None, "enabled": True},
    ]

    listed = client.get(f"/api/v1/projects/{project_id}/rules")
    assert listed.status_code == 200
    assert [item["revision"] for item in listed.json()] == [1]

    before_active = client.get(f"/api/v1/projects/{project_id}/rules/active")
    assert before_active.status_code == 404

    activated = client.post(f"/api/v1/projects/{project_id}/rules/1/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    active = client.get(f"/api/v1/projects/{project_id}/rules/active")
    assert active.status_code == 200
    assert active.json()["revision"] == 1
    assert active.json()["status"] == "active"


def test_project_rule_preview_is_non_persistent_and_keeps_canonical_text(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)
    source = "Official Media presents Model 700 today."

    preview = client.post(
        f"/api/v1/projects/{project_id}/rules/preview",
        json={
            "text": source,
            "rules": [
                {"kind": "speech_suppress", "match": "Official Media"},
                {
                    "kind": "pronunciation",
                    "match": "Model 700",
                    "replacement": "Model seven hundred",
                },
                {
                    "kind": "entity_alias",
                    "match": "Model 700",
                    "replacement": "flagship domestic off-road SUV",
                },
                {
                    "kind": "semantic_hint",
                    "hint": "prefer formal launch and media coverage",
                },
            ],
        },
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body["canonical_text"] == source
    assert body["speech_text"] == " presents Model seven hundred today."
    assert body["subtitle_text"] == source
    assert body["retrieval_text"] == (
        source + " flagship domestic off-road SUV"
    )
    assert body["semantic_hints"] == ["prefer formal launch and media coverage"]

    listed = client.get(f"/api/v1/projects/{project_id}/rules")
    assert listed.status_code == 200
    assert listed.json() == []


def test_project_rule_analyze_returns_candidates_without_persisting(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)
    analyzer = RecordingRuleAnalyzer()
    client.app.state.project_rule_analyzer = analyzer
    source = "Official Media字幕保留但旁白不要念；Model 700读成Model seven hundred。"

    response = client.post(
        f"/api/v1/projects/{project_id}/rules/analyze",
        json={"text": source},
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_text": source,
        "rules": [
            {
                "kind": "speech_suppress",
                "match": "Official Media",
                "replacement": None,
                "hint": None,
                "enabled": True,
            },
            {
                "kind": "pronunciation",
                "match": "Model 700",
                "replacement": "Model seven hundred",
                "hint": None,
                "enabled": True,
            },
        ],
    }
    assert analyzer.calls == [source]
    assert client.get(f"/api/v1/projects/{project_id}/rules").json() == []


def test_project_rule_analyze_returns_404_for_unknown_project_without_calling_analyzer(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    analyzer = RecordingRuleAnalyzer()
    client.app.state.project_rule_analyzer = analyzer

    response = client.post(
        f"/api/v1/projects/{uuid4()}/rules/analyze",
        json={"text": "batch rules"},
    )

    assert response.status_code == 404
    assert analyzer.calls == []


def test_project_rule_analyze_returns_503_when_analyzer_is_unavailable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)
    client.app.state.project_rule_analyzer = None

    response = client.post(
        f"/api/v1/projects/{project_id}/rules/analyze",
        json={"text": "batch rules"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "project rule analyzer is not configured"


def test_project_rule_routes_return_404_for_unknown_project_or_revision(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing = uuid4()

    assert client.get(f"/api/v1/projects/{missing}/rules").status_code == 404
    assert (
        client.post(
            f"/api/v1/projects/{missing}/rules/drafts",
            json={"rules": []},
        ).status_code
        == 404
    )

    project_id = _create_project(client)
    assert client.post(f"/api/v1/projects/{project_id}/rules/99/activate").status_code == 404


def test_project_rule_api_rejects_invalid_rule_shape(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _create_project(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/rules/drafts",
        json={
            "rules": [
                {
                    "kind": "pronunciation",
                    "match": "Model 700",
                }
            ]
        },
    )

    assert response.status_code == 422
