import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function worker(network, cached) {
  const handlers = {}, writes = [];
  const cache = {match:async()=>cached,put:async(key)=>writes.push(key),addAll:async()=>{},add:async()=>{}};
  vm.runInNewContext(readFileSync(new URL('../public/sw.js',import.meta.url),'utf8'), {
    self:{location:{origin:'http://localhost'},addEventListener:(name,handler)=>handlers[name]=handler},
    caches:{open:async()=>cache},fetch:network,URL,Response,Headers,Promise,
  });
  function fetchEvent(path, method='GET') {
    let response;
    handlers.fetch({request:{url:'http://localhost'+path,method,mode:'cors'},respondWith:p=>response=p});
    return response;
  }
  return {fetchEvent,writes};
}

test('private records and mutations never enter the service worker cache',()=>{
  const w=worker(()=>{throw Error('must not intercept');});
  for(const path of ['/api/profile','/api/schemes','/api/conversations/session','/api/documents/audio/test.wav','/api/export/json','/healthz']) assert.equal(w.fetchEvent(path),undefined);
  assert.equal(w.fetchEvent('/api/consent','POST'),undefined);
});
test('public catalog uses the fresh network result and updates its cache',async()=>{
  const w=worker(async()=>new Response('{"fresh":true}',{status:200}));
  const response=await w.fetchEvent('/api/catalog/schemes?lang=hi-IN');
  assert.deepEqual(await response.json(),{fresh:true}); assert.equal(w.writes.length,1);
});
test('offline public guide returns an explicitly labelled saved response',async()=>{
  const w=worker(async()=>{throw Error('offline');},new Response('{"saved":true}',{headers:{'Content-Type':'application/json'}}));
  const response=await w.fetchEvent('/api/guides/health?lang=hi-IN');
  assert.equal(response.headers.get('X-Offline-Cache'),'true');
  assert.deepEqual(await response.json(),{saved:true});
});
test('offline uncached content returns an actionable 503',async()=>{
  const w=worker(async()=>{throw Error('offline');});
  const response=await w.fetchEvent('/api/guides/health?lang=hi-IN');
  assert.equal(response.status,503); assert.match((await response.json()).detail,/not been saved/);
});
test('server errors do not silently replay stale success',async()=>{
  const w=worker(async()=>new Response('failed',{status:500}),new Response('old success'));
  const response=await w.fetchEvent('/api/guides/health?lang=hi-IN');
  assert.equal(response.status,500); assert.equal(w.writes.length,0);
});
