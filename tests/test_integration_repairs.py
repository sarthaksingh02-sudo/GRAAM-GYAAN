import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import db, assistant, conversation, sarvam_client
from backend.main import app
from backend.routers import documents, voice, knowledge


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "test.db"))
    monkeypatch.setenv("SARVAM_MOCK", "true")
    monkeypatch.setenv("DEMO_CACHE", "0")
    for module in (assistant, documents, voice, knowledge):
        monkeypatch.setattr(module, "BASE_DIR", tmp_path)
    with TestClient(app) as client:
        # Exercise the real problem: first household's ID is not 1.
        conn = db.get_conn()
        conn.execute("INSERT INTO users(id,village,district,state,consent_given) VALUES(9,'Test','Pune','Maharashtra',1)")
        conn.execute("INSERT INTO family_members(user_id,name,dob,relation,gender,occupation,education_level) VALUES(9,'Test Farmer','1980-01-01','self','male','farmer','secondary')")
        conn.commit(); conn.close()
        yield client


def test_consistent_household(client):
    assert client.get('/api/profile').json()['household']['id'] == 9
    missing = client.get('/api/missing-documents').json()
    assert missing['householdId'] == 9 and missing['totalMissingMandatory'] > 0
    assert client.get('/api/export/json').json()['household']['id'] == 9
    schemes = client.get('/api/schemes').json()['schemes']
    assert next(s for s in schemes if s['id'] == 'mgnrega')['eligibility']['matchedMember'] is not None


def test_location_does_not_substitute_varanasi(client):
    result = client.get('/api/projects?district=Pune&state=Maharashtra').json()
    assert result['missing_data'] and result['district'] == 'Pune'
    assert result['centre'] == []
    assert not assistant.tool_get_regional_projects(9)['sources']


def test_chat_greeting_audio_and_history(client):
    result = client.post('/api/chat', json={'message':'Hello','lang':'en-IN','sessionId':'repair-test'}).json()
    assert 'Hello' in result['text'] and 'scheme for you' not in result['text']
    assert result['isMock'] and result['mode'] == 'mock'
    audio = client.get(result['audioUrl'])
    assert audio.status_code == 200 and audio.content[:4] == b'RIFF'
    assert len(client.get('/api/conversations/repair-test').json()['turns']) == 2


def test_unknown_query_does_not_recommend_random_scheme(client):
    result = client.post('/api/chat', json={'message':'astronomy galaxies','lang':'en-IN'}).json()
    assert not result['sources']


def test_live_grounded_history_and_citations(client, monkeypatch):
    client.post('/api/chat', json={'message':'Hello','lang':'en-IN','sessionId':'history'})
    captured = []
    fake = SimpleNamespace(chat=lambda messages, **kw: captured.extend(messages) or {'content':json.dumps({'text':'Apply at the Gram Panchayat.','source_ids':['scheme:mgnrega']})})
    result = conversation.grounded_answer(9,'history','How do I apply?','en-IN',fake)
    assert len(captured) >= 4 and captured[-1]['content'] == 'How do I apply?'
    assert 'eligibility' in captured[0]['content'] and 'Pune' in captured[0]['content']
    assert result['sources'][0]['url'] == 'https://nrega.nic.in'
    fake.chat = lambda *a, **kw: {'content':'{"text":"Made up","source_ids":["invented"]}'}
    with pytest.raises(ValueError): conversation.grounded_answer(9,'history','test','en-IN',fake)


def test_unconfigured_is_not_mock(monkeypatch):
    monkeypatch.setenv('SARVAM_MOCK','false'); monkeypatch.setenv('DEMO_CACHE','0'); monkeypatch.setenv('SARVAM_API_KEY','')
    client = sarvam_client.SarvamClient()
    assert not client.mock and client.mode == 'unconfigured'
    with pytest.raises(RuntimeError): client.chat([{'role':'user','content':'Hello'}])


def test_consent_and_invalid_fields(client):
    assert client.post('/api/consent',json={'village':'Test'}).status_code == 400
    result = assistant.tool_update_profile(9,'consent_given = 0 --','x',confirmed=True)
    assert 'Invalid' in result['text']
    assert client.post('/api/chat',json={'message':''}).status_code == 422
    assert client.get('/api/profile',headers={'X-User-Id':'bad'}).status_code == 400


def test_voice_preserves_container_and_removes_recording(client, monkeypatch):
    captured = []
    def transcribe(self,path,**kwargs):
        captured.append(Path(path)); assert Path(path).suffix == '.webm'
        return {'transcript':'Hello'}
    monkeypatch.setattr(sarvam_client.SarvamClient,'transcribe',transcribe)
    response = client.post('/api/voice',files={'file':('recording.webm',b'webm fixture','audio/webm')},data={'lang':'en-IN'})
    assert response.status_code == 200
    assert not captured[0].exists()


def test_document_review_saves_fields_and_is_idempotent(client):
    image = io.BytesIO(); Image.new('RGB',(100,100),'white').save(image,format='PNG')
    response = client.post('/api/documents',files={'file':('ration.png',image.getvalue(),'image/png')})
    job_id = response.json()['jobId']
    job = client.get('/api/documents/'+job_id).json()
    assert job['status'] == 'ready' and job['extractedFields']
    approved = client.post(f'/api/documents/{job_id}/confirm',json={'fields':[], 'createFamilyMembers':True})
    assert approved.status_code == 200
    again = client.post(f'/api/documents/{job_id}/confirm',json={'fields':[]})
    assert again.json()['documentId'] == approved.json()['documentId']
    conn = db.get_conn()
    assert conn.execute('SELECT count(*) FROM extracted_fields').fetchone()[0] > 0
    path = conn.execute('SELECT file_path FROM document_jobs WHERE job_id=?',(job_id,)).fetchone()[0]
    conn.close()
    assert not Path(path).exists()


def test_nested_identifier_redaction():
    from backend.privacy import redact_identifiers
    result = redact_identifiers({'members':[{'note':'ID 1234 5678 9012 and ABCDE1234F'}]})
    assert '9012' not in json.dumps(result) and 'ABCDE1234F' not in json.dumps(result)


def test_document_provider_schema():
    from backend.config_loader import get_doc_schema
    schema = sarvam_client._extract_schema(get_doc_schema('ration_card'))
    assert schema['type'] == 'object'
    assert schema['properties']['members']['items']['type'] == 'object'


def test_confirmation_requires_prior_proposal_and_cancel_wins(client):
    action = {'tool':'update_profile','field':'village','value':'Changed'}
    first = client.post('/api/chat',json={'sessionId':'confirm','message':'yes','confirmAction':action}).json()
    assert first['requiresConfirmation']
    assert client.get('/api/profile').json()['household']['village'] == 'Test'
    client.post('/api/chat',json={'sessionId':'confirm','message':'no, do not confirm','confirmAction':first['pendingAction']})
    assert client.get('/api/profile').json()['household']['village'] == 'Test'
    proposal = client.post('/api/chat',json={'sessionId':'confirm','message':'please change','confirmAction':action}).json()
    client.post('/api/chat',json={'sessionId':'confirm','message':'yes','confirmAction':proposal['pendingAction']})
    assert client.get('/api/profile').json()['household']['village'] == 'Changed'


def test_offline_catalog_contains_no_personal_eligibility(client):
    data = client.get('/api/catalog/schemes').json()
    assert data['catalogOnly']
    assert all(s['status'] == 'NOT_EVALUATED' for s in data['schemes'])
    assert 'Test Farmer' not in json.dumps(data)


def test_recommendations_filter_ineligible_and_rank_relevance(client):
    data = client.get('/api/suggestions?query=mgnrega').json()
    assert data['suggestions'][0]['id'] == 'mgnrega'
    assert all(s['eligibility']['status'] != 'NOT_ELIGIBLE' for s in data['suggestions'])


def test_history_keeps_source_metadata(client):
    client.post('/api/chat',json={'sessionId':'sources','message':'MGNREGA scheme','lang':'en-IN'})
    turns = client.get('/api/conversations/sources').json()['turns']
    assert turns[-1]['sources'] and turns[-1]['mode'] == 'mock'


def test_incomplete_policy_never_claims_confirmed_eligibility(client):
    schemes = client.get('/api/schemes').json()['schemes']
    assert all(s['status'] != 'ELIGIBLE' for s in schemes)
    for scheme_id in ('ayushman_bharat', 'pmay_g'):
        item = next(s for s in schemes if s['id'] == scheme_id)
        assert item['status'] == 'POSSIBLE'
        assert item['eligibility']['missingFields']
