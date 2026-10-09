import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { request, jsonRequest, safeUrl } from './api';
import './style.css';

function App() {
  const [lang, setLang] = useState(localStorage.getItem('language') || 'hi-IN');
  const hi = lang.startsWith('hi');
  const t = (h, e) => hi ? h : e;
  const [languages, setLanguages] = useState([]);
  const [health, setHealth] = useState(undefined);
  const [online, setOnline] = useState(navigator.onLine);
  const [profile, setProfile] = useState(undefined);
  const [tiles, setTiles] = useState([]);
  const [chips, setChips] = useState([]);
  const [view, setView] = useState('home');
  const [content, setContent] = useState(null);
  const [regional, setRegional] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState('');
  const [schemeQuery, setSchemeQuery] = useState('');
  const [rankedIds, setRankedIds] = useState(null);
  const [pending, setPending] = useState(null);
  const [recording, setRecording] = useState(false);
  const [job, setJob] = useState(null);
  const [fields, setFields] = useState([]);
  const [memberId, setMemberId] = useState('');
  const [createMembers, setCreateMembers] = useState(false);
  const [member, setMember] = useState(null);
  const [location, setLocation] = useState({});
  const [consent, setConsent] = useState(false);
  const [drafts, setDrafts] = useState(() => {try {return JSON.parse(localStorage.getItem('pending-profile-edits') || '[]');} catch {return []}});
  const session = useRef(sessionStorage.getItem('chat-session') || crypto.randomUUID());
  const recorder = useRef(null);
  const timer = useRef(null);
  const recordingCancel = useRef(false);
  const chatLock = useRef(false);
  const lastMessage = useRef(null);

  async function refreshProfile() {
    try {const p = await request('/api/profile'); setProfile(p); setLocation(p.household); setConsent(!!p.household.consentGiven); return p;}
    catch (e) {if ([401,403,404].includes(e.status)) setProfile(null); if (navigator.onLine) setError(e.message);}
  }
  async function loadStatus() {
    try {setHealth(await request('/healthz'));} catch {setHealth(null);}
  }
  useEffect(() => {
    sessionStorage.setItem('chat-session', session.current);
    refreshProfile(); loadStatus();
    request('/api/languages').then(d => setLanguages(d.supported_languages || [])).catch(e => setError(e.message));
    request(`/api/conversations/${session.current}`).then(d => setMessages((d.turns || []).map(m => ({...m, isMock:m.isMock})))).catch(() => {});
    const update = () => {setOnline(navigator.onLine); loadStatus();};
    window.addEventListener('online', update); window.addEventListener('offline', update);
    if ('serviceWorker' in navigator && import.meta.env.PROD) navigator.serviceWorker.register('/sw.js').catch(e => setError(e.message));
    return () => {window.removeEventListener('online', update); window.removeEventListener('offline', update); stopRecording(true);};
  }, []);
  useEffect(() => {
    localStorage.setItem('language', lang);
    document.documentElement.lang = lang.split('-')[0];
    request(`/api/home-tiles?lang=${lang}`).then(d => setTiles(d.tiles || [])).catch(e => setError(e.message));
    request(`/api/intents?lang=${lang}`).then(d => setChips(d.chips || [])).catch(e => setError(e.message));
    if (view !== 'home' && !['chat','profile','family','scan'].includes(view)) openView(view);
  }, [lang]);
  useEffect(() => {lastMessage.current?.scrollIntoView({block:'nearest'});}, [messages, busy]);
  useEffect(() => {localStorage.setItem('pending-profile-edits', JSON.stringify(drafts));}, [drafts]);

  async function openView(next) {
    stopRecording(true); setError(''); setView(next); setContent(null); setRankedIds(null); setSchemeQuery('');
    if (next === 'profile' || next === 'family') {await refreshProfile(); return;}
    if (['home','chat','scan'].includes(next)) return;
    setBusy(true);
    try {const route = next === "schemes" && (!online || !profile) ? "catalog/schemes" : next; setContent(await request(`/api/${route}?lang=${lang}`));} catch (e) {setError(e.message);} finally {setBusy(false);}
  }
  useEffect(() => {
    if (!profile || !['home','projects','schemes'].includes(view)) return;
    let cancelled = false;
    let poll;
    setRegional(null);
    async function load() {
      try {const data = await request('/api/region-feed'); if (!cancelled) {setRegional(data); if(data.refreshing) poll=setTimeout(load,3000);}}
      catch(e) {if(!cancelled) setRegional({status:'unavailable',errors:[e.message]});}
    }
    load();
    return () => {cancelled=true;clearTimeout(poll);};
  }, [profile,view]);
  async function refreshRegion() {
    try {setRegional(await request('/api/region-feed?refresh=true')); await refreshProfile();} catch(e) {setError(e.message);}
  }
  function RegionalFeed() {
    if(!profile || !['home','projects','schemes'].includes(view)) return null;
    const data=regional;
    const items=view==='schemes' ? data?.schemes : data?.projects;
    return <section className="panel"><h2>{t('आपके क्षेत्र के आधिकारिक अपडेट','Official updates for your region')}</h2>
      <p>{[profile.household.village,profile.household.block,profile.household.district,profile.household.state].filter(Boolean).join(' · ')}</p>
      <button disabled={data?.refreshing} onClick={refreshRegion}>{data?.refreshing ? t('स्रोत जाँचे जा रहे हैं…','Checking sources…') : t('अभी अपडेट करें','Refresh official sources')}</button>
      {data?.checkedAt && <p><small>{t('स्रोत जाँचा गया','Source checked')}: {new Date(data.checkedAt).toLocaleString()} · {data.status==='stale' ? 'STALE — refresh failed' : 'District coverage'}</small></p>}
      <p>{t('जिला सूचनाएँ गाँव में चल रहे काम का प्रमाण नहीं हैं। गाँव के काम के लिए eGramSwaraj में अपना स्थान चुनें।','District notices do not confirm active works in your village. Select your location on eGramSwaraj for panchayat work reports.')}</p>
      {data?.errors?.map((e,i)=><p className="notice" key={i}>{e}</p>)}
      {(items || []).slice(0,view==='home'?3:30).map(item=><article className="card" key={item.id}><small>{item.type==='scheme'?'SCHEME LISTING':'PROJECT / TENDER NOTICE'} · {item.scope}</small><h3><a href={safeUrl(item.url)} target="_blank" rel="noreferrer">{item.title}</a></h3><p>{item.excerpt!==item.title ? item.excerpt : ''}</p>{item.publishedDate && <small>Source listing date: {item.publishedDate}</small>}</article>)}
      {data && !data.refreshing && !items?.length && <p>{t('इस स्रोत में मिलते रिकॉर्ड नहीं मिले। नीचे आधिकारिक पोर्टल देखें।','No matching records found in this source. Browse the official portals below.')}</p>}
      <Sources sources={(data?.portals || []).map(p=>({name:p.title,url:p.url}))}/>
      <small>{data?.freshnessNote}</small>
    </section>;
  }
  function Sources({sources}) {
    return <div className="sources">{sources?.filter(s => s.name || s.url || s.sourceUrl).map((s, i) => <span key={i}><a href={safeUrl(s.url || s.sourceUrl)} target="_blank" rel="noreferrer">{s.name || t('आधिकारिक स्रोत','Official source')}</a>{(s.verified_date || s.verifiedDate) && <small> · {t('स्रोत तिथि','Source date')}: {s.verified_date || s.verifiedDate}</small>}</span>)}</div>;
  }
  async function listen(message,index) {
    setBusy(true);setError('');
    try {const audio=await jsonRequest('/api/speech','POST',{sessionId:session.current,text:message.text,lang});setMessages(current=>current.map((m,i)=>i===index?{...m,...audio}:m));}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function send(text = query, action = pending) {
    if (!text.trim() || chatLock.current) return;
    if (!online) {setError(t('सहायक के लिए इंटरनेट चाहिए। सहेजी गई गाइड पढ़ सकते हैं।','Chat needs a connection. Saved guides remain available.')); return;}
    chatLock.current = true; setBusy(true); setError(''); setQuery(''); setView('chat');
    setMessages(m => [...m, {role:'user', text}]);
    try {
      const response = await jsonRequest('/api/chat', 'POST', {message:text, sessionId:session.current, lang, confirmAction:action, includeAudio:false});
      setMessages(m => [...m, {role:'assistant', ...response}]); setPending(response.pendingAction || null);
      if (action && !response.requiresConfirmation) await refreshProfile();
    } catch (e) {setError(e.message); setQuery(text);} finally {chatLock.current = false; setBusy(false);}
  }
  function stopRecording(cancel = false) {
    recordingCancel.current = cancel; clearTimeout(timer.current);
    if (recorder.current?.state === 'recording') recorder.current.stop();
    setRecording(false);
  }
  async function record() {
    if (recording) {stopRecording(); return;}
    setError('');
    if (!online || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {setError(t('माइक्रोफ़ोन उपलब्ध नहीं है। टाइप करें।','Microphone unavailable. Please type your question.')); return;}
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio:true});
      const mime = ['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(x => MediaRecorder.isTypeSupported(x));
      const rec = new MediaRecorder(stream, mime ? {mimeType:mime} : undefined); recorder.current = rec;
      const chunks = []; recordingCancel.current = false;
      rec.ondataavailable = e => {if(e.data.size) chunks.push(e.data);};
      rec.onstop = async () => {
        stream.getTracks().forEach(track => track.stop()); setRecording(false); clearTimeout(timer.current);
        if (recordingCancel.current || !chunks.length) return;
        const type = rec.mimeType; const extension = type.includes('mp4') ? 'mp4' : type.includes('ogg') ? 'ogg' : 'webm';
        const form = new FormData(); form.append('file', new Blob(chunks,{type}), `recording.${extension}`); form.append('sessionId',session.current); form.append('lang',lang);
        setBusy(true); chatLock.current = true;
        try {const data = await request('/api/voice',{method:'POST',body:form}); setMessages(m => [...m,{role:'user',text:data.transcript},{role:'assistant',...data.assistant}]); setPending(data.assistant.pendingAction || null);}
        catch(e) {setError(e.message);} finally {setBusy(false); chatLock.current=false;}
      };
      rec.start(); setRecording(true); timer.current = setTimeout(() => stopRecording(), 30000);
    } catch(e) {stream?.getTracks().forEach(track => track.stop()); setError(e.message);}
  }
  async function saveLocation(e) {
    e.preventDefault(); setError('');
    const data = {...location, language_pref:lang};
    if (!profile && !consent) {setError(t('पहले सहमति दें।','Please accept consent first.')); return;}
    if (!online && profile) {setDrafts(d => [...d,{path:'/api/profile',method:'PUT',data,householdId:profile.household.id}]); setError(t('बदलाव डिवाइस पर लंबित है। ऑनलाइन होने पर समन्वय करें।','Change saved on this device as pending. Sync when online.')); return;}
    setBusy(true);
    try {await jsonRequest(profile ? '/api/profile' : '/api/consent',profile ? 'PUT' : 'POST',profile ? data : {...data,consent}); await refreshProfile(); session.current=crypto.randomUUID(); sessionStorage.setItem('chat-session',session.current); setMessages([]); setPending(null); setRegional(null); setView('home');}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function saveMember(e) {
    e.preventDefault(); setBusy(true); setError('');
    try {const {id,...data}=member; await jsonRequest(id ? `/api/family/${id}` : '/api/family',id ? 'PUT' : 'POST',data); await refreshProfile(); setMember(null);}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function syncDrafts() {
    setBusy(true); setError('');
    try {const current = await request('/api/profile'); for (const draft of drafts) {if (draft.householdId !== current.household.id) throw new Error('Pending changes belong to another household.'); await jsonRequest(draft.path,draft.method,draft.data); setDrafts(d => d.slice(1));} await refreshProfile();}
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function upload(file) {
    if (!file) return; setBusy(true); setError(''); setJob(null); setFields([]);
    const form = new FormData(); form.append('file',file); form.append('lang',lang);
    try {
      const {jobId} = await request('/api/documents',{method:'POST',body:form});
      const deadline = Date.now()+180000;
      while(Date.now()<deadline) {
        const data = await request(`/api/documents/${jobId}`); setJob(data);
        if(data.status === 'failed') throw new Error(data.error || 'Document processing failed.');
        if(data.status === 'ready') {setFields(data.extractedFields.map(f => ({...f, edit: typeof f.value === 'object' && f.value !== null ? JSON.stringify(f.value,null,2) : String(f.value ?? '')}))); setCreateMembers(false); return;}
        await new Promise(resolve => setTimeout(resolve,1500));
      }
      throw new Error('Document is taking longer than expected. Please retry later.');
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function approveDocument() {
    setBusy(true); setError('');
    try {
      const reviewed = fields.map(f => ({key:f.key,value:typeof f.value === 'object' && f.value !== null ? JSON.parse(f.edit) : f.edit}));
      await jsonRequest(`/api/documents/${job.jobId}/confirm`,'POST',{fields:reviewed,createFamilyMembers:createMembers,memberId:memberId ? Number(memberId) : null});
      setJob({...job,approved:true}); await refreshProfile();
    } catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function exportData(format) {
    setError('');
    try {
      const response = await fetch(`/api/export/${format}?lang=${lang}`);
      if(!response.ok) throw new Error('Export failed. Please retry.');
      if(format==='text') {await navigator.clipboard.writeText(await response.text()); setError(t('सारांश कॉपी हुआ।','Summary copied.')); return;}
      const url=URL.createObjectURL(await response.blob()); const a=document.createElement('a'); a.href=url; a.download=`graam-gyaan.${format}`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(e) {setError(e.message);}
  }
  const icons = {talk:'🎙️', scan_document:'📷', my_family:'👨‍👩‍👧‍👦', schemes:'🌾', projects:'🏗️'};
  const modeLabel = !online ? t('ऑफ़लाइन · सहेजी गाइड','Offline · saved guides') : health === undefined ? t('कनेक्ट हो रहा है…','Connecting…') : !health ? t('सर्वर उपलब्ध नहीं','Server unavailable') : health.mode==='live' ? t('AI कनेक्शन कॉन्फ़िगर है','AI connection configured') : health.mode==='unconfigured' ? t('AI कुंजी सेट करें','AI key required') : `${health.mode.toUpperCase()} · ${t('परीक्षण उत्तर','test responses')}`;
  return <>
    <header><a className="brand" href="#" onClick={e=>{e.preventDefault();openView('home');}}>🌾 <span>ग्राम-ज्ञान<small>GRAAM-GYAAN</small></span></a><select aria-label="Language" value={lang} onChange={e=>setLang(e.target.value)}>{languages.length ? languages.map(l=><option key={l.code} value={l.code}>{l.native_name}</option>) : <><option value="hi-IN">हिन्दी</option><option value="en-IN">English</option></>}</select></header>
    <main>
      <div className={`connection ${health?.mode==='live' && online ? '' : 'warning'}`}>{modeLabel}</div>
      <section className="village"><div><small>{t('आपका गाँव और परिवार','Your village & household')}</small><h1>{profile ? [profile.household.village,profile.household.district].filter(Boolean).join(', ') : t('ग्राम-ज्ञान में स्वागत है','Welcome to GRAAM-GYAAN')}</h1>{profile?.familyMembers.some(m=>m.name.includes('(TEST)')) && <span className="badge">{t('नमूना परिवार · अपनी जानकारी संपादित करें','Sample household · edit to use your details')}</span>}</div><button onClick={()=>openView('profile')}>{t('प्रोफाइल संपादित करें','Edit profile')}</button></section>
      {drafts.length>0 && <div className="notice">{drafts.length} {t('लंबित बदलाव','pending changes')} <button disabled={!online||busy} onClick={syncDrafts}>{t('समन्वय करें','Sync changes')}</button><button onClick={()=>setDrafts([])}>{t('रद्द करें','Discard')}</button></div>}
      {error && <div role="alert" className="error">{error}<button aria-label="Dismiss" onClick={()=>setError('')}>×</button></div>}
      {view !== 'home' && <button className="back" onClick={()=>openView('home')}>← {t('मुख्य पृष्ठ','Home')}</button>}
      {profile === null && view==='home' && <div className="notice">{t('सहायक और दस्तावेज़ों के लिए सहमति देकर अपना परिवार जोड़ें।','Accept consent and set up your household to use the assistant and documents.')} <button onClick={()=>openView('profile')}>{t('शुरू करें','Get started')}</button></div>}
      {view==='home' && <><h2>{t('आज हम कैसे मदद करें?','How can we help today?')}</h2><div className="chips">{chips.map(c=><button key={c.id} disabled={!profile||busy} onClick={()=>send(c.text,null)}>{c.text}</button>)}</div><div className="tiles">{tiles.map(tile=><button key={tile.id} onClick={()=>openView(({talk:'chat',scan_document:'scan',my_family:'family'})[tile.id] || (tile.guideTopic ? `guides/${tile.guideTopic}` : tile.id))}><span>{icons[tile.id] || '📖'}</span><strong>{tile.label}</strong></button>)}<button onClick={()=>openView('guides/health')}><span>🩺</span><strong>{t('स्वास्थ्य मार्गदर्शन','Health guidance')}</strong></button><button onClick={()=>openView('guides/livelihood')}><span>🧰</span><strong>{t('आजीविका मार्गदर्शन','Livelihood guidance')}</strong></button></div></>}
      {view==='profile' && <section className="panel"><h2>{t('परिवार का स्थान','Household location')}</h2><form onSubmit={saveLocation}>{[['village','गाँव','Village'],['panchayat','पंचायत','Panchayat'],['block','ब्लॉक','Block'],['tehsil','तहसील','Tehsil'],['village_code','गाँव जनगणना कोड','Census village code'],['district','जिला (English नाम)','District (English name)'],['state','राज्य (English नाम)','State (English name)']].map(([key,h,e])=><label key={key}>{t(h,e)}<input required={['village','district','state'].includes(key)} value={location[key] || ''} onChange={e=>setLocation({...location,[key]:e.target.value})}/></label>)}<p>{t('दस्तावेज़ AI सेवा को भेजे जाते हैं। मूल स्कैन प्रसंस्करण के बाद हटते हैं। पहचान संख्या दर्ज न करें।','Documents are sent to the AI service. Original scans are removed after processing. Do not enter identification numbers here.')}</p>{!profile && <label className="check"><input type="checkbox" required checked={consent} onChange={e=>setConsent(e.target.checked)}/>{t('मैं परिवार की जानकारी प्रसंस्करण और सहेजने की सहमति देता/देती हूँ।','I consent to processing and saving this household’s information.')}</label>}<button className="primary" disabled={busy}>{t('सुरक्षित करें','Save')}</button></form></section>}
      {health?.ephemeralStorage && <p className="notice">Free demo: saved household data and audio may reset when the server restarts. Use sample information.</p>}
      <RegionalFeed/>
      {view==='chat' && <section className="panel"><h2>{t('अपने सहायक से पूछें','Ask your assistant')}</h2><div className="conversation" aria-live="polite">{!messages.length && <p>{t('योजनाओं, दस्तावेज़ों और अपने परिवार के बारे में बोलें या लिखें।','Speak or type about schemes, documents, and your household.')}</p>}{messages.map((m,i)=><article key={i} className={`message ${m.role}`}><small>{m.role==='user' ? t('आप','You') : t('सहायक','Assistant')}{m.isMock || m.mode==='demo' ? ' · DEMO / MOCK' : m.mode==='fallback' ? ' · SAVED-SOURCE FALLBACK' : ''}</small><p>{m.text}</p><Sources sources={m.sources}/>{m.role==='assistant' && !m.audioUrl && <button disabled={busy} onClick={()=>listen(m,i)}>{t('उत्तर सुनें','Listen to answer')}</button>}{m.audioUrl && <audio controls src={m.audioUrl} preload="none" onError={()=>setError(t('ऑडियो नहीं चल सका। नीचे उत्तर पढ़ें।','Audio could not be played. Read the answer above.'))}/>} {m.audioError && <small>{m.audioError}</small>}</article>)}{busy && <p role="status">{t('उत्तर तैयार हो रहा है…','Preparing your answer…')}</p>}<div ref={lastMessage}/></div>{pending && <div className="notice"><p>{t('ऊपर दिए बदलाव की पुष्टि करें।','Confirm the proposed change above.')}</p><button disabled={busy} onClick={()=>send('हाँ, पुष्टि करें',pending)}>{t('पुष्टि करें','Confirm')}</button><button disabled={busy} onClick={()=>send('नहीं, रद्द करें',pending)}>{t('रद्द करें','Cancel')}</button></div>}<form className="composer" onSubmit={e=>{e.preventDefault();send();}}><input aria-label="Your question" placeholder={t('अपना सवाल लिखें…','Type your question…')} value={query} onChange={e=>setQuery(e.target.value)} maxLength={4000}/><button className="primary" disabled={busy||recording||!profile}>{t('भेजें','Send')}</button></form><button className={recording?'recording':''} disabled={busy||!profile} onClick={record}>{recording ? t('⏹ रोकें और भेजें','⏹ Stop and send') : t('🎙️ बोलें','🎙️ Speak')}</button><button disabled={busy||recording} onClick={()=>{session.current=crypto.randomUUID();sessionStorage.setItem('chat-session',session.current);setMessages([]);setPending(null);}}>{t('नई बातचीत','New conversation')}</button></section>}
      {view==='family' && <section className="panel"><h2>{t('मेरा परिवार','My family')}</h2><button disabled={!profile} onClick={()=>setMember({name:'',relation:'self',dob:'',occupation:'',gender:'',education_level:''})}>{t('+ सदस्य जोड़ें','+ Add member')}</button>{profile?.familyMembers.map(m=><article className="card" key={m.id}><h3>{m.name} <small>({m.relation})</small></h3><p>{m.ageYears ?? '—'} {t('वर्ष','years')} · {m.occupation || '—'}</p><p>{t('बाकी दस्तावेज़','Missing documents')}: {m.missingDocuments.filter(d=>d.mandatory).map(d=>d.title).join(', ') || t('कोई नहीं','None')}</p><button onClick={()=>setMember({id:m.id,name:m.name,relation:m.relation,dob:m.dob||'',gender:m.gender||'',occupation:m.occupation||'',education_level:m.education_level||'',land_acres:m.land_acres||0})}>{t('संपादित करें','Edit')}</button></article>)}{member && <form onSubmit={saveMember} className="card"><h3>{t('सदस्य विवरण','Member details')}</h3>{['name','relation','dob','occupation','education_level','land_acres'].map(k=><label key={k}>{({name:t('नाम','Name'),relation:t('संबंध','Relation'),dob:t('जन्म तिथि','Date of birth'),occupation:t('व्यवसाय','Occupation'),education_level:t('शिक्षा','Education'),land_acres:t('भूमि (एकड़)','Land (acres)')})[k]}<input type={k==='dob'?'date':k==='land_acres'?'number':'text'} min={k==='land_acres'?'0':undefined} step={k==='land_acres'?'0.01':undefined} required={['name','relation'].includes(k)} value={member[k] ?? ''} onChange={e=>setMember({...member,[k]:k==='land_acres'?Number(e.target.value):e.target.value})}/></label>)}<label>{t('लिंग','Gender')}<select value={member.gender} onChange={e=>setMember({...member,gender:e.target.value})}><option value="">—</option><option value="female">{t('महिला','Female')}</option><option value="male">{t('पुरुष','Male')}</option><option value="other">{t('अन्य','Other')}</option></select></label><button disabled={busy} className="primary">{t('सुरक्षित करें','Save')}</button><button type="button" onClick={()=>setMember(null)}>{t('रद्द करें','Cancel')}</button></form>}</section>}
      {view==='scan' && <section className="panel"><h2>{t('दस्तावेज़ स्कैन और समीक्षा','Scan and review a document')}</h2><p>{t('JPG, PNG या PDF · अधिकतम 10 MB / 10 पृष्ठ। मूल फ़ाइल प्रसंस्करण के बाद हटती है।','JPG, PNG or PDF · up to 10 MB / 10 pages. Original files are deleted after processing.')}</p><input aria-label="Document upload" type="file" accept="image/jpeg,image/png,application/pdf" disabled={busy||!profile||!online} onChange={e=>upload(e.target.files[0])}/>{job && <p role="status">{job.isMock || job.mode==='demo' ? 'DEMO / MOCK · ' : ''}{job.status}</p>}{fields.map((f,i)=><label key={f.key}>{f.label}<textarea disabled={job?.approved} value={f.edit} onChange={e=>setFields(fields.map((item,j)=>j===i?{...item,edit:e.target.value}:item))}/></label>)}{job?.noticeDetails && <article className="card"><p>{job.noticeDetails.summary}</p><p>{t('अंतिम तिथि','Deadline')}: {job.noticeDetails.deadline || t('उल्लेख नहीं है','Not specified')}</p><ul>{job.noticeDetails.whatToDo?.map((s,i)=><li key={i}>{s}</li>)}</ul></article>}{job?.status==='ready' && !job.approved && <><label>{t('परिवार सदस्य से जोड़ें','Link to family member')}<select value={memberId} onChange={e=>setMemberId(e.target.value)}><option value="">{t('परिवार का मुखिया / नया सदस्य','Household head / new member')}</option>{profile?.familyMembers.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>{fields.some(f=>f.key==='members') && <label className="check"><input type="checkbox" checked={createMembers} onChange={e=>setCreateMembers(e.target.checked)}/>{t('समीक्षा की गई सूची से परिवार सदस्य जोड़ें','Create family members from the reviewed list')}</label>}<button className="primary" disabled={busy} onClick={approveDocument}>{t('समीक्षा करके सुरक्षित करें','Approve reviewed information')}</button></>}{job?.approved && <p className="notice">✓ {t('दस्तावेज़ सुरक्षित हुआ।','Document saved.')}</p>}</section>}
      {view==='schemes' && content && <section><h2>{t('सरकारी योजनाएं','Welfare schemes')}</h2>{content.catalogOnly && <p className="notice">{t("सहेजी गई योजनाएं। परिवार की पात्रता जांचने के लिए ऑनलाइन प्रोफाइल जोड़ें।","Saved scheme catalog. Connect and set up your profile to evaluate eligibility.")}</p>}<p>{t('पात्रता सहेजी गई जानकारी पर आधारित है। आधिकारिक स्वीकृति की गारंटी नहीं है।','Eligibility uses saved information; it is not a guarantee of official approval.')}</p>{online && profile && <form className="composer" onSubmit={async e=>{e.preventDefault();setError('');try{const result=await request(`/api/suggestions?query=${encodeURIComponent(schemeQuery)}&lang=${lang}`);setRankedIds(result.suggestions.map(s=>s.id));}catch(err){setError(err.message);}}}><input aria-label="Find relevant schemes" value={schemeQuery} onChange={e=>setSchemeQuery(e.target.value)} placeholder={t('बेटी, किसान, रोजगार…','Daughter, farmer, employment…')}/><button>{t('सुझाव खोजें','Find suggestions')}</button></form>}{rankedIds?.length===0 && <p>{t('इस खोज के लिए पात्र या संभावित योजना नहीं मिली।','No eligible or possible schemes matched this search.')}</p>}{(rankedIds ? rankedIds.map(id=>content.schemes.find(s=>s.id===id)).filter(Boolean) : content.schemes)?.map(s=><article className="card" key={s.id}><span className={`badge ${s.status}`}>{({ELIGIBLE:t("दर्ज शर्तें पूरी","Recorded checks met"),POSSIBLE:t("आधिकारिक जाँच बाकी","Verification required"),NOT_ELIGIBLE:t("दर्ज शर्तें पूरी नहीं","Recorded checks not met"),NOT_EVALUATED:t("पात्रता जाँची नहीं गई","Eligibility not evaluated")})[s.status]}</span><h3>{s.name}</h3><p>{s.benefit}</p>{s.eligibility.matchedMember && <p>{t('संबंधित सदस्य','Matching member')}: {s.eligibility.matchedMember.name}</p>}{s.eligibility.preliminary && <p>{t('यह शुरुआती जाँच है। पूरा सत्यापन संबंधित कार्यालय में कराएं।','These are preliminary checks. Complete verification at the responsible office.')}</p>}{s.eligibility.missingFields?.map((f,i)=><p key={i}>{f.question}</p>)}<details><summary>{t('आवेदन कैसे करें','How to apply')}</summary><h4>{t("आवश्यक दस्तावेज़","Required documents")}</h4><ul>{s.documentsRequired?.map((d,i)=><li key={i}>{typeof d === "string" ? d : d.title || d.name}</li>)}</ul><ol>{s.steps?.map((step,i)=><li key={i}>{typeof step === "string" ? step : step.description || step.title}</li>)}</ol></details><Sources sources={[{...s,url:s.sourceUrl}]}/><button disabled={!profile||busy} onClick={()=>send(`${s.name}: ${t('आवेदन कैसे करें?','How do I apply?')}`,null)}>{t('सहायक से पूछें','Ask assistant')}</button></article>)}</section>}
      {view==='projects' && content && <section><h2>{t('क्षेत्र के विकास कार्य','Local development projects')}</h2><p>{content.district}, {content.stateName}</p>{content.missing_data && <p>{content.message}</p>}{['centre','state'].map(group=><div key={group}><h3>{group==='centre'?t('केंद्र सरकार','Central government'):t('राज्य सरकार','State government')}</h3>{content[group]?.map(p=><article className="card" key={p.id}><h3>{p.name}</h3><p>{p.description}</p><small>{p.agency} · {p.status}</small></article>)}</div>)}<Sources sources={[{url:content.sourceUrl,verified_date:content.verifiedDate}]}/></section>}
      {view.startsWith('guides/') && content && <section className="panel"><h2>{content.title}</h2>{content.offline && <p className="notice">{t('सहेजी गई ऑफ़लाइन प्रति','Saved offline copy')}</p>}{content.steps?.map((s,i)=><article className="card" key={s.id||i}><h3>{i+1}. {s.title}</h3><p>{s.description}</p></article>)}<Sources sources={[{url:content.sourceUrl,verified_date:content.verifiedDate}]}/></section>}
      {busy && view!=='chat' && <p role="status">{t('कृपया प्रतीक्षा करें…','Please wait…')}</p>}
      <footer><p>{t('स्रोतों के साथ जानकारी। पहचान संख्या साझा न करें।','Information with sources. Do not share identification numbers.')}</p><button disabled={!profile||!online} onClick={()=>exportData('pdf')}>PDF</button><button disabled={!profile||!online} onClick={()=>exportData('text')}>{t('सारांश कॉपी करें','Copy summary')}</button><button disabled={!profile||!online} onClick={()=>exportData('json')}>JSON</button></footer>
    </main>
  </>;
}
createRoot(document.getElementById('root')).render(<App/>);
