// Experimental shared-desktop adapter. Observed Windows ZCode 3.17.1 only.
import http from 'node:http';
import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { writeFile, mkdir } from 'node:fs/promises';

const METHODS = new Set(['getSessionLifecycle', 'conversationRowsRangeV4']);
export async function startLocalAdapter({ BrowserWindow, attachWorkspaceHost,
  releaseAttachment, makeClient, workspacePath, sessionId, stateDirectory }) {
  if (!workspacePath || !sessionId || !/^sess_[a-zA-Z0-9-]+$/.test(sessionId) || !stateDirectory) throw new Error('Explicit workspace and state directory required');
  const token = randomBytes(32).toString('hex');
  const attachments = new Map();
  const server = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    const reply = (status, body) => { res.writeHead(status); res.end(JSON.stringify(body)); };
    const supplied = Buffer.from(req.headers.authorization ?? '');
    const expected = Buffer.from(`Bearer ${token}`);
    if (req.headers.origin || supplied.length !== expected.length || !timingSafeEqual(supplied, expected))
      return reply(403, { error: 'forbidden' });
    if (req.method !== 'POST' || req.url !== '/rpc') return reply(404, { error: 'not_found' });
    try {
      let bytes = 0; const parts = [];
      for await (const part of req) {
        bytes += part.length;
        if (bytes > 65536) return reply(413, { error: 'request_too_large' });
        parts.push(part);
      }
      const request = JSON.parse(Buffer.concat(parts).toString('utf8'));
      if (request.action === 'windows') return reply(200, { windows: BrowserWindow.getAllWindows().map(w => ({ id: w.id, title: w.getTitle() })) });
      if (request.action === 'attach') {
        if (!Number.isInteger(request.windowId) || !BrowserWindow.fromId(request.windowId)) throw new Error('Unknown window');
        const entry = await attachWorkspaceHost(request.windowId, { kind: 'local', workspacePath });
        let client, attached;
        try {
          client = makeClient(entry.port);
          const channel = client.getChannel('zcode-agent');
          const clientId = `codex-local-${randomUUID()}`;
          const hello = await channel.call('helloConversationV4', []);
          await channel.call('initializeConversationV4', [{kind:'clientHello',protocolVersion:3,clientId,clientKind:'web',appVersion:'local-adapter',capabilities:{historyFirst:true,workspaceHookReviewUi:true}}]);
          attached = { entry, client, clientId, frames: [], sequence: 0 };
          attachments.set(entry.attachmentId, attached);
          if (sessionId) {
            attached.listener = channel.listen('onDynamicConversationFrame', {workspacePath})(frame => {
              attached.frames.push({sequence:++attached.sequence,frame});
              if (attached.frames.length > 200) attached.frames.shift();
            });
            attached.subscription = await channel.call('subscribeConversationV4', [{workspacePath,sessionId}]);
          }
          return reply(200, { attachmentId: entry.attachmentId, workspacePath, sessionId, hello, subscription:attached.subscription });
        } catch (error) {
          attachments.delete(entry.attachmentId);
          attached?.listener?.dispose();
          client?.dispose();
          releaseAttachment(entry.attachmentId);
          throw error;
        }
      }
      const attached = attachments.get(request.attachmentId);
      if (!attached) throw new Error('Unknown attachment');
      if (request.action === 'detach') {
        attachments.delete(request.attachmentId);
        attached.listener?.dispose();
        attached.client.dispose(); releaseAttachment(attached.entry.attachmentId);
        return reply(200, { detached: true });
      }
      if (request.action === 'events') return reply(200, { frames: attached.frames.filter(f => f.sequence > (request.afterSequence ?? 0)).map(f => ({sequence:f.sequence})), nextSequence:attached.sequence });
      if (request.action === 'send') {
        if (!sessionId || typeof request.text !== 'string' || !request.text.trim() || request.text.length > 8192) throw new Error('Invalid text or unconfigured session');
        const envelope = {commandId:request.commandId ?? randomUUID(),clientId:attached.clientId,sessionId,type:'sendText',payload:{text:request.text},issuedAt:Date.now()};
        return reply(200, { result: await attached.client.getChannel('zcode-agent').call('sendConversationCommandV4', [{workspacePath,envelope}]) });
      }
      if (request.action !== 'call' || !METHODS.has(request.method)) throw new Error('Method is not allowed');
      const args = request.args ?? {};
      if (sessionId && args.sessionId !== sessionId) throw new Error('Session is pinned');
      if (Object.keys(args).some(k => !['sessionId', 'beforeRowId', 'limit'].includes(k))) throw new Error('Unexpected argument');
      if (typeof args.sessionId !== 'string' || !/^sess_[a-zA-Z0-9-]+$/.test(args.sessionId)) throw new Error('Explicit session ID required');
      if (args.limit !== undefined && (!Number.isInteger(args.limit) || args.limit < 1 || args.limit > 30)) throw new Error('Invalid row limit');
      const result = await Promise.race([
        attached.client.getChannel('zcode-agent').call(request.method, [{ ...args, workspacePath }]),
        new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('RPC timeout')), 15000); timer.unref(); })
      ]);
      if (request.method === 'conversationRowsRangeV4' && Array.isArray(result?.rows)) {
        result.rows = result.rows.filter(row => ['assistantText', 'userInput', 'toolCall'].includes(row.kind));
      }
      reply(200, { result });
    } catch (error) { reply(400, { error: error instanceof Error ? error.message : 'request_failed' }); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  await mkdir(stateDirectory, { recursive: true, mode: 0o700 });
  await writeFile(`${stateDirectory}/connection.json`, JSON.stringify({ port: server.address().port, token, pid: process.pid, workspacePath }), { mode: 0o600 });
  return { async dispose() {
    for (const { entry, client, listener } of attachments.values()) { listener?.dispose(); client.dispose(); releaseAttachment(entry.attachmentId); }
    attachments.clear(); await new Promise(resolve => server.close(resolve));
  }};
}
