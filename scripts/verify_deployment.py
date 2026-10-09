"""Verify the public Vercel-to-Render integration with synthetic browser sessions."""
import json
import time
import httpx

BASE="https://graam-gyaan-three.vercel.app"
with httpx.Client(base_url=BASE, timeout=60) as first, httpx.Client(base_url=BASE, timeout=30) as second:
    health=first.get("/healthz")
    health.raise_for_status()
    assert health.json()["mode"] == "live", health.text
    print("Vercel -> Render health: live", flush=True)
    consent=first.post("/api/consent",json={"village":"Demo village","panchayat":"Demo panchayat","block":"Sirkoni","district":"Jaunpur","state":"Uttar Pradesh","consent":True})
    assert consent.status_code == 200, consent.text
    assert first.get("/api/profile").json()["household"]["village"] == "Demo village"
    assert second.get("/api/profile").status_code in (403,404)
    print("Isolated household sessions: PASS",flush=True)
    for query in ("Hello", "Tell me about MGNREGA", "How do I apply for it?"):
        started=time.monotonic()
        response=first.post("/api/chat",json={"message":query,"sessionId":"public-verification","lang":"en-IN","includeAudio":False})
        assert response.status_code == 200,response.text
        answer=response.json()
        assert answer["mode"] == "live",answer
        assert not answer["audioUrl"]
        print(json.dumps({"query":query,"answer":answer["text"],"sources":len(answer["sources"]),"seconds":round(time.monotonic()-started,1)}),flush=True)
    speech=first.post("/api/speech",json={"sessionId":"public-verification","text":answer["text"],"lang":"en-IN"})
    assert speech.status_code == 200,speech.text
    audio=speech.json()["audioUrl"]
    assert first.get(audio).status_code == 200
    assert second.get(audio).status_code in (403,404)
    print("On-demand speech + private audio: PASS",flush=True)
    first.get("/api/region-feed?refresh=true").raise_for_status()
    for attempt in range(15):
        regional=first.get("/api/region-feed").json()
        if not regional.get("refreshing"):break
        time.sleep(2)
    print(json.dumps({"region":"Jaunpur","status":regional["status"],"schemes":len(regional.get("schemes",[])),"projects":len(regional.get("projects",[])),"errors":regional.get("errors")}),flush=True)
    first.put("/api/profile",json={"village":"Demo Pune village","panchayat":"","block":"","district":"Pune","state":"Maharashtra"}).raise_for_status()
    region=first.get("/api/region-feed").json()
    assert region["region"]["district"] == "Pune"
    assert all(item.get("district")=="Pune" for item in region.get("projects",[]))
    print("Location switching without cross-region records: PASS",flush=True)
    print("PUBLIC DEPLOYMENT VERIFIED",flush=True)
