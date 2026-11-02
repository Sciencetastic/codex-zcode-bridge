import { startLocalAdapter } from './adapter.mjs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';

const stateDirectory = await mkdtemp(join(tmpdir(), 'zcode-adapter-test-'));
const calls = []; const released = [];
const adapter = await startLocalAdapter({
  BrowserWindow: { getAllWindows: () => [{ id: 7, getTitle: () => 'Disposable test' }], fromId: id => id === 7 },
  attachWorkspaceHost: async (windowId, scope) => { calls.push({ windowId, scope }); return { attachmentId: 'mock-port', port: {} }; },
  releaseAttachment: id => released.push(id),
  makeClient: () => ({ dispose() {}, getChannel: name => ({ listen: () => () => ({dispose(){}}), call: async (method, args) => { calls.push({ name, method, args }); return method === 'conversationRowsRangeV4' ? {rows:[{kind:'reasoning',text:'PRIVATE_TEST_ONLY'},{kind:'assistantText',text:'Visible reply'},{kind:'unknown',text:'UNKNOWN_TEST_ONLY'}]} : { state: 'idle' }; } }) }),
  workspacePath: 'TEST_WORKSPACE', sessionId:'sess_test-123', stateDirectory
});
try {
  const connection = JSON.parse(await readFile(join(stateDirectory, 'connection.json'), 'utf8'));
  const request = async (body, extra = {}, authorized = true) => {
    const response = await fetch(`http://127.0.0.1:${connection.port}/rpc`, { method: 'POST', headers: { ...(authorized ? { authorization: `Bearer ${connection.token}` } : {}), ...extra }, body: JSON.stringify(body) });
    return { status: response.status, body: await response.json() };
  };
  assert.equal((await request({ action: 'windows' }, {}, false)).status, 403);
  assert.equal((await request({ action: 'windows' }, { origin: 'https://untrusted.example' })).status, 403);
  assert.equal((await request({ action: 'windows' })).status, 200);
  assert.equal((await request({ action: 'attach', windowId: 99 })).status, 400);
  assert.equal((await request({ action: 'attach', windowId: 7 })).status, 200);
  const base = { action: 'call', attachmentId: 'mock-port', args: { sessionId: 'sess_test-123' } };
  assert.equal((await request({ ...base, method: 'sendConversationCommandV4' })).status, 400);
  assert.equal((await request({ ...base, method: 'getSessionLifecycle', args: { ...base.args, workspacePath: 'OTHER' } })).status, 400);
  assert.equal((await request({ ...base, method: 'getSessionLifecycle', args: {sessionId:'sess_OTHER'} })).status, 400);
  assert.equal((await request({ ...base, method: 'getSessionLifecycle' })).status, 200);
  assert.deepEqual(calls.at(-1).args, [{ sessionId: 'sess_test-123', workspacePath: 'TEST_WORKSPACE' }]);
  const visible = await request({...base, method:'conversationRowsRangeV4'});
  assert.deepEqual(visible.body.result.rows,[{kind:'assistantText',text:'Visible reply'}]);
  assert.equal((await request({action:'send',attachmentId:'mock-port',text:'Harmless test'})).status,200);
  assert.equal(calls.at(-1).method,'sendConversationCommandV4');
  assert.equal(calls.at(-1).args[0].envelope.sessionId,'sess_test-123');
  assert.equal((await request({action:'send',attachmentId:'mock-port',text:'x'.repeat(8193)})).status,400);
  assert.equal((await request({ action: 'detach', attachmentId: 'mock-port' })).status, 200);
  assert.deepEqual(released, ['mock-port']);
  console.log('PASS: authentication, browser-origin rejection, workspace pinning, method restriction, pinned send envelope, hidden-row filtering, attachment release. Mocked host only.');
} finally { await adapter.dispose(); await rm(stateDirectory, { recursive: true, force: true }); }
