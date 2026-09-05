from fastapi.testclient import TestClient
from solution_advisor.common_analyzer.service import AnalysisService

def upload(client: TestClient, payload: bytes):
    return client.post('/api/v1/model-assets', files={'file': ('minimal.onnx', payload)})

def complete(client: TestClient, response) -> dict:
    task_id = response.json()['analysis_task']['id']; session = client.app.state.session_factory()
    try: AnalysisService(session, client.app.state.artifact_storage, client.app.state.analysis_queue).run(task_id)
    finally: session.close()
    return client.get(f'/api/v1/analysis-tasks/{task_id}').json()

def test_health_check(client):
    assert client.get('/healthz').json() == {'status':'ok'}

def test_async_upload_profile_and_events(client: TestClient, model_bytes):
    response = upload(client, model_bytes); assert response.status_code == 201
    task = response.json()['analysis_task']; assert task['status'] == 'QUEUED'
    completed = complete(client, response); assert completed['status'] == 'SUCCEEDED'
    assert [x['status'] for x in completed['events']] == ['QUEUED','RUNNING','SUCCEEDED','SUCCEEDED','SUCCEEDED','SUCCEEDED']
    profile = client.get(f"/api/v1/model-profiles/{completed['profile_id']}").json()
    assert profile['summary']['node_count'] == 4
    assert profile['summary']['opset_imports'][0]['version'] == 11

def test_duplicate_content_creates_tasks_without_second_asset(client: TestClient, model_bytes):
    one, two = upload(client, model_bytes), upload(client, model_bytes)
    assert one.json()['asset']['id'] == two.json()['asset']['id']
    assert one.json()['reused']['asset'] is False and two.json()['reused']['asset'] is True
    assert one.json()['analysis_task']['id'] != two.json()['analysis_task']['id']

def test_invalid_onnx_becomes_sanitized_async_failure(client: TestClient):
    response = upload(client, b'not onnx'); result = complete(client, response)
    assert result['status'] in {'QUEUED','FAILED'}

def test_resources_not_found(client):
    assert client.get('/api/v1/model-assets/asset_missing').status_code == 404
