"""Opt-in live verification using only a synthetic household and synthetic document."""
from pathlib import Path
import base64
import json
import os
import sys
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
work = root / '.cache' / 'live-verification' / uuid.uuid4().hex
work.mkdir(parents=True)
os.environ['DATABASE_URL'] = str(work / 'test.db')
os.environ['SARVAM_MOCK'] = 'false'
os.environ['DEMO_CACHE'] = '0'

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from backend import assistant
from backend.main import app
from backend.routers import documents, voice, knowledge
from backend.sarvam_client import SarvamClient

for module in (assistant, documents, voice, knowledge):
    module.BASE_DIR = work
results = []
with TestClient(app) as api:
    api.post('/api/consent', json={'village':'Synthetic test village','district':'Pune','state':'Maharashtra','consent':True})
    api.post('/api/family', json={'name':'Synthetic Test Adult','dob':'1980-01-01','relation':'self','occupation':'farmer','gender':'male'})
    for query in ['Hello', 'Tell me about MGNREGA', 'How do I apply for it?']:
        response = api.post('/api/chat', json={'message':query,'lang':'en-IN','sessionId':'live-verification'})
        data = response.json()
        assert response.status_code == 200, data
        assert not data['isMock'] and data['mode'] == 'live'
        if query != 'Hello': assert data['sources'], data
        assert data['audioUrl'] and api.get(data['audioUrl']).status_code == 200, data
        print(json.dumps({'query':query,'answer':data['text'],'audio':'200','mode':data['mode']},ensure_ascii=True),flush=True)
    client = SarvamClient()
    speech = client.synthesize('What documents are needed for MGNREGA?', language_code='en-IN', use_cache=False)
    response = api.post('/api/voice', files={'file':('test.wav',base64.b64decode(speech['audio_b64']),'audio/wav')},data={'lang':'en-IN'})
    assert response.status_code == 200, response.text
    print('STT voice flow:',response.json()['transcript'],flush=True)
    image = Image.new('RGB',(1300,500),'white')
    draw = ImageDraw.Draw(image)
    draw.text((35,60),'PUBLIC NOTICE - SYNTHETIC TEST\nVillage meeting on 15 November 2026 at the community hall.\nBring your application form. Issued by Test Gram Panchayat.',fill='black',font_size=30)
    scan = work / 'synthetic_notice.png'; image.save(scan)
    with scan.open('rb') as file:
        response = api.post('/api/documents', files={'file':(scan.name,file,'image/png')},data={'lang':'en-IN'})
    assert response.status_code == 202, response.text
    job = api.get('/api/documents/'+response.json()['jobId']).json()
    assert job['status'] == 'ready', job
    assert job['noticeDetails'] and job['noticeDetails']['summary'], job
    print('Document OCR and notice extraction:',json.dumps(job['noticeDetails'],ensure_ascii=True),flush=True)
    # Verify the Extract API schema separately using the same synthetic notice.
    from backend.config_loader import get_doc_schema
    extracted = client.doc_extract(scan, get_doc_schema('official_notice'), doc_type='official_notice', language='en-IN')
    assert extracted['status'] in ('completed','partially_completed') and extracted.get('result'), extracted
    print('Structured document Extract: PASS',flush=True)
print('Live verification passed. Synthetic artifacts:',work,flush=True)
