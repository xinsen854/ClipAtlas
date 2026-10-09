from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.providers.errors import ProviderStructuredOutputError


def test_structured_failure_has_specific_code_and_preserves_actionable_detail():
    app=FastAPI()
    register_error_handlers(app)

    @app.get('/failure')
    def failure():
        raise ProviderStructuredOutputError('actions: list_type; request_id=fixture')

    response=TestClient(app).get('/failure')
    assert response.status_code==502
    assert response.json()['error']=={
        'code':'provider_invalid_structured_output',
        'message':'actions: list_type; request_id=fixture',
    }
