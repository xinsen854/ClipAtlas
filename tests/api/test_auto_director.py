from clipatlas.main import create_app


def test_auto_director_routes_are_registered():
    paths = create_app().openapi()["paths"]

    assert "/api/v1/projects/{project_id}/auto-director/readiness" in paths
    assert "/api/v1/auto-director/analyze" in paths
    assert "/api/v1/projects/{project_id}/auto-director/outlines" in paths
    assert "/api/v1/auto-director/outlines/{outline_id}" in paths
    assert "/api/v1/auto-director/outlines/{outline_id}/confirm" in paths
