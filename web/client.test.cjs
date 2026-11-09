// Offline checks for the actual inline page script; uses Node's built-in APIs only.
// Run: node --test web/client.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const SID = '123e4567-e89b-42d3-a456-426614174000';

class Element {
  constructor(text = '') {
    this.children = []; this.attributes = {}; this.listeners = {}; this.dataset = {};
    this.hidden = false; this.disabled = false; this.value = ''; this._text = text; this.className = '';
    this.classList = {remove() {}};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(_) { throw new Error('Untrusted content must never use innerHTML'); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = (this.scrolled || 0) + 1; }
}

// fetch 里发给 /api/session 的请求单独处理，这样 asks 只记录 /api/ask。
function fixture(ask, {history = {ok: true, json: async () => ({turns: []})}, storage = new Map(), noStorage = false} = {}) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const examples = [new Element('提问示例')];
  for (const id of ['source-list', 'source-detail', 'error']) elements.get(id).hidden = true; // 与 HTML 里的 hidden 属性一致
  const sessionCalls = [];
  const fetch = async (url, options = {}) => {
    if (String(url).startsWith('/api/session/')) {
      sessionCalls.push({url, method: options.method || 'GET'});
      return options.method === 'DELETE' ? {ok: true} : history;
    }
    return ask(url, options);
  };
  const localStorage = noStorage ? {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }}
    : {getItem: key => storage.has(key) ? storage.get(key) : null, setItem: (key, value) => storage.set(key, value)};
  let generated = 0;
  const crypto = {randomUUID: () => `00000000-0000-4000-8000-${String(++generated).padStart(12, '0')}`};
  const context = vm.createContext({
    document: {getElementById: id => elements.get(id), querySelectorAll: () => examples,
      createElement: () => new Element(), createTextNode: text => new Element(text)},
    fetch, TextDecoder, Uint8Array, AbortController, setTimeout, clearTimeout, localStorage, crypto,
  });
  vm.runInContext(script, context);
  const messages = elements.get('messages');
  const part = (msg, name) => msg.children.find(c => c.className.split(' ').includes(name));
  return {elements, context, storage, sessionCalls, messages, part,
    ready: vm.runInContext('ready', context),
    assistants: () => messages.children.filter(m => m.className.includes('assistant')),
    users: () => messages.children.filter(m => m.className.includes('user')),
    submit: () => elements.get('ask-form').listeners.submit({preventDefault() {}})};
}

const done = (overrides = {}) => ({answer: '收入123元[2]', refused: false, refusal_reason: '', error: '',
  citations: [{n: 2, doc_id: 'test-report', title: '测试财报', page: 6, section: '财务数据', kind: 'table', text: '收入123元'}],
  unverified_numbers: [], partial: false, usage: {input_tokens: 12, output_tokens: 34, cost_yuan: .0001}, ...overrides});
function sse(parts, final, newline = '\n', extra = []) {
  return [...extra, ...parts.map(text => ['token', {text}]), ['done', final]].map(([kind, data]) =>
    `event: ${kind}${newline}data: ${JSON.stringify(data)}${newline}${newline}`).join('');
}
function response(text, singleBytes = false) {
  const bytes = new TextEncoder().encode(text);
  const chunks = singleBytes ? [...bytes].map(b => new Uint8Array([b])) : [bytes];
  return {ok: true, body: new ReadableStream({start(controller) {
    for (const chunk of chunks) controller.enqueue(chunk);
    controller.close();
  }})};
}

test('fragmented UTF-8 and CRLF SSE render correct text and original citation number', async () => {
  const f = fixture(async () => response(sse(['收入', '123元[2]'], done(), '\r\n'), true));
  f.elements.get('question').value = '  营业收入  ';
  await f.submit();
  const msg = f.assistants()[0];
  assert.equal(f.part(msg, 'bubble').textContent, '收入123元[2]');
  assert.equal(f.elements.get('status').textContent, '回答完成');
  assert.match(f.part(msg, 'usage').textContent, /输入 12 Token.*输出 34 Token/);
  assert.equal(f.users()[0].textContent, '营业收入');
  assert.equal(f.elements.get('question').value, '');
  const citation = f.part(msg, 'bubble').children.find(el => el.className === 'citation');
  assert.equal(citation.textContent, '[2]'); citation.listeners.click();
  assert.equal(f.elements.get('source-title').textContent, '测试财报');
  assert.match(f.elements.get('source-meta').textContent, /PDF 第 6 页/);
  assert.equal(f.elements.get('pdf-link').href, '/api/pdf/test-report#page=6');
  assert.equal(f.elements.get('submit').disabled, false);
  assert.ok(msg.scrolled >= 1, 'new answer scrolls into view');
});

test('request carries the session_id and it is stored; a stored id is reused', async () => {
  const bodies = [];
  const f = fixture(async (_, options) => { bodies.push(JSON.parse(options.body)); return response(sse([], done())); });
  f.elements.get('question').value = '问题'; await f.submit();
  assert.match(bodies[0].session_id, /^[0-9a-f-]{36}$/);
  assert.equal(f.storage.get('finrag.session_id'), bodies[0].session_id);
  const g = fixture(async (_, options) => { bodies.push(JSON.parse(options.body)); return response(sse([], done())); },
    {storage: new Map([['finrag.session_id', SID]])});
  g.elements.get('question').value = '问题'; await g.submit();
  assert.equal(bodies[1].session_id, SID);
});

test('blocked localStorage falls back to an in-memory session id', async () => {
  const bodies = [];
  const f = fixture(async (_, options) => { bodies.push(JSON.parse(options.body)); return response(sse([], done())); }, {noStorage: true});
  f.elements.get('question').value = '问题'; await f.submit();
  assert.match(bodies[0].session_id, /^[0-9a-f-]{36}$/);
});

test('rewritten question is shown above the answer as text', async () => {
  const rewritten = ['rewritten', {question: '比亚迪2025年的净利润是多少？'}];
  const f = fixture(async () => response(sse(['收入123元[2]'], done({rewritten: '比亚迪2025年的净利润是多少？', clarify: false}), '\n', [rewritten])));
  f.elements.get('question').value = '那利润呢？'; await f.submit();
  const note = f.part(f.assistants()[0], 'rewritten');
  assert.equal(note.hidden, false);
  assert.equal(note.textContent, '我理解的问题是：比亚迪2025年的净利润是多少？');
  const plain = fixture(async () => response(sse(['收入123元[2]'], done({rewritten: '', clarify: false}))));
  plain.elements.get('question').value = '问题'; await plain.submit();
  assert.equal(plain.part(plain.assistants()[0], 'rewritten').hidden, true);
});

test('clarify reply is an ordinary assistant message', async () => {
  const f = fixture(async () => response(sse([], done({answer: '您想了解哪家公司？目前可以查询：比亚迪。', citations: [], clarify: true, rewritten: ''}))));
  f.elements.get('question').value = '营业收入多少？'; await f.submit();
  const msg = f.assistants()[0];
  assert.equal(f.part(msg, 'bubble').textContent, '您想了解哪家公司？目前可以查询：比亚迪。');
  assert.equal(msg.hidden, false);
  assert.equal(f.elements.get('source-list').hidden, true);
  assert.equal(f.elements.get('error').hidden, true);
});

test('citations of an earlier message show that turn\'s source text', async () => {
  let n = 0;
  const texts = ['第一轮原文', '第二轮原文'];
  const f = fixture(async () => {
    const text = texts[n++];
    return response(sse([], done({answer: `答案[1]`, citations: [{n: 1, doc_id: 'd' + n, title: 't' + n, page: n, section: '', kind: 'text', text}]})));
  });
  for (const q of ['一', '二']) { f.elements.get('question').value = q; await f.submit(); }
  assert.equal(f.elements.get('source-text').textContent, '第二轮原文');
  const first = f.assistants()[0];
  f.part(first, 'bubble').children.find(el => el.className === 'citation').listeners.click();
  assert.equal(f.elements.get('source-text').textContent, '第一轮原文');
  assert.equal(f.elements.get('pdf-link').href, '/api/pdf/d1#page=1');
});

test('history is loaded on page start', async () => {
  const turns = [
    {question: '比亚迪营收？', rewritten: '', answer: '营收123元[2]', status: 'answered',
      citations: [{n: 2, doc_id: 'test-report', title: '测试财报', page: 6, section: '', kind: 'text', text: '原文123'}]},
    {question: '那利润呢？', rewritten: '比亚迪2025年的净利润是多少？', answer: '', status: 'refused', citations: []},
    {question: '营业收入多少？', rewritten: '', answer: '您想了解哪家公司？', status: 'clarify', citations: []},
  ];
  const f = fixture(async () => { throw new Error('no ask expected'); },
    {history: {ok: true, json: async () => ({turns})}, storage: new Map([['finrag.session_id', SID]])});
  await f.ready;
  assert.deepEqual(f.sessionCalls, [{url: `/api/session/${SID}`, method: 'GET'}]);
  assert.equal(f.users().length, 3);
  assert.deepEqual(f.users().map(u => u.textContent), ['比亚迪营收？', '那利润呢？', '营业收入多少？']);
  const [a1, a2, a3] = f.assistants();
  assert.equal(f.part(a1, 'bubble').textContent, '营收123元[2]');
  assert.equal(f.part(a2, 'rewritten').textContent, '我理解的问题是：比亚迪2025年的净利润是多少？');
  assert.match(f.part(a2, 'bubble').textContent, /证据不足|无法/);
  assert.equal(f.part(a3, 'bubble').textContent, '您想了解哪家公司？');
  f.part(a1, 'bubble').children.find(el => el.className === 'citation').listeners.click();
  assert.equal(f.elements.get('source-text').textContent, '原文123');
});

test('failed history load starts an empty conversation', async () => {
  for (const history of [{ok: false, status: 404}, {ok: true, json: async () => { throw new Error('bad'); }}]) {
    const f = fixture(async () => response(sse([], done())), {history});
    await f.ready;
    assert.equal(f.messages.children.length, 0); assert.equal(f.elements.get('empty').hidden, false);
  }
});

test('new conversation deletes the old session, clears the list and uses a new id', async () => {
  const bodies = [];
  const f = fixture(async (_, options) => { bodies.push(JSON.parse(options.body)); return response(sse([], done())); },
    {storage: new Map([['finrag.session_id', SID]])});
  f.elements.get('question').value = '问题'; await f.submit();
  assert.equal(f.messages.children.length, 2);
  f.elements.get('new-chat').listeners.click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(f.messages.children.length, 0);
  assert.equal(f.elements.get('source-list').hidden, true);
  assert.ok(f.sessionCalls.some(c => c.method === 'DELETE' && c.url === `/api/session/${SID}`));
  assert.notEqual(f.storage.get('finrag.session_id'), SID);
  f.elements.get('question').value = '再问'; await f.submit();
  assert.equal(bodies[1].session_id, f.storage.get('finrag.session_id'));
});

test('final refusal replaces provisional text and removes citations', async () => {
  const f = fixture(async () => response(sse(['暂时显示的错误回答'], done({refused: true, refusal_reason: 'no_valid_citation', answer: ''}))));
  f.elements.get('question').value = '营业收入'; await f.submit();
  const bubble = f.part(f.assistants()[0], 'bubble');
  assert.doesNotMatch(bubble.textContent, /暂时显示/);
  assert.match(bubble.textContent, /缺少有效引用/);
  assert.equal(f.elements.get('source-list').hidden, true);
});

test('untrusted answer, rewrite, history and source stay text', async () => {
  const attack = '<img src=x onerror=alert(1)>';
  const data = done({answer: attack + '[2]', unverified_numbers: ['9999'], rewritten: attack,
    citations: [{n: 2, doc_id: 'report /中', title: attack, page: 7, section: attack, text: attack, kind: 'text'}]});
  const f = fixture(async () => response(sse([attack], data)));
  f.elements.get('question').value = attack; await f.submit();
  const msg = f.assistants()[0];
  assert.equal(f.users()[0].textContent, attack);
  assert.equal(f.part(msg, 'bubble').textContent, attack + '[2]');
  assert.equal(f.part(msg, 'rewritten').textContent, '我理解的问题是：' + attack);
  assert.equal(f.elements.get('source-text').textContent, attack);
  assert.equal(f.elements.get('source-title').textContent, attack);
  assert.equal(f.elements.get('pdf-link').href, '/api/pdf/report%20%2F%E4%B8%AD#page=7');
  assert.equal(f.part(msg, 'warning').hidden, false);
  assert.match(f.part(msg, 'warning').textContent, /9999/);
  // 从历史恢复的文字同样不经过 innerHTML。
  const turns = [{question: attack, rewritten: attack, answer: attack, status: 'answered', citations: []}];
  const g = fixture(async () => { throw new Error('unused'); }, {history: {ok: true, json: async () => ({turns})}});
  await g.ready;
  assert.equal(g.users()[0].textContent, attack);
  assert.equal(g.part(g.assistants()[0], 'bubble').textContent, attack);
});

test('done error hides the provisional answer without displaying raw error', async () => {
  const f = fixture(async () => response(sse(['未完成内容'], done({error: 'sk-secret F:/private'}))));
  f.elements.get('question').value = '问题'; await f.submit();
  const msg = f.assistants()[0];
  assert.equal(msg.hidden, true); assert.equal(f.part(msg, 'bubble').textContent, '');
  assert.equal(f.elements.get('error').textContent, '回答生成失败，请稍后重试。');
  assert.equal(f.elements.get('question').value, '问题');
});

test('missing done or malformed JSON rejects provisional answer and unlocks submit', async () => {
  for (const body of ['event: token\ndata: {"text":"不完整"}\n\n', 'event: done\ndata: invalid\n\n']) {
    const f = fixture(async () => response(body)); f.elements.get('question').value = '问题'; await f.submit();
    assert.equal(f.part(f.assistants()[0], 'bubble').textContent, '');
    assert.equal(f.assistants()[0].hidden, true);
    assert.match(f.elements.get('error').textContent, /连接中断/);
    assert.equal(f.elements.get('submit').disabled, false);
  }
});

test('busy state prevents duplicate submission and sends a trimmed question', async () => {
  let resolve, calls = 0;
  const f = fixture((_, options) => {
    calls++; assert.equal(JSON.parse(options.body).question, '问题');
    return new Promise(r => {resolve = r;});
  });
  await f.ready;
  f.elements.get('question').value = '  问题  ';
  const pending = f.submit();
  assert.equal(f.elements.get('submit').disabled, true);
  assert.equal(f.elements.get('new-chat').disabled, true);
  await f.submit(); assert.equal(calls, 1);
  resolve(response(sse([], done()))); await pending;
  assert.equal(f.elements.get('submit').disabled, false);
});

test('input rejects empty/overlong values; HTTP failure allows retry', async () => {
  let calls = 0;
  const f = fixture(async () => { calls++; return {ok: false, status: 422}; });
  for (const value of ['   ', '问'.repeat(501)]) {
    f.elements.get('question').value = value; await f.submit();
  }
  assert.equal(calls, 0);
  f.elements.get('question').value = '问题'; await f.submit();
  assert.equal(calls, 1); assert.equal(f.elements.get('submit').disabled, false);
  assert.match(f.elements.get('error').textContent, /1–500/);
});

test('429 shows the server message as text and falls back when the body is unusable', async () => {
  const cases = [
    [{ok: false, status: 429, json: async () => ({error: 'rate_limited', message: '请求太频繁，请 30 秒后再试。'})}, '请求太频繁，请 30 秒后再试。'],
    [{ok: false, status: 429, json: async () => { throw new Error('not json'); }}, '请求太频繁，请稍后再试。'],
    [{ok: false, status: 429, json: async () => ({message: 42})}, '请求太频繁，请稍后再试。'],
    [{ok: false, status: 500}, '请求失败，请稍后重试。'],
  ];
  for (const [res, expected] of cases) {
    const f = fixture(async () => res);
    f.elements.get('question').value = '问题'; await f.submit();
    assert.equal(f.elements.get('error').textContent, expected);
    assert.equal(f.elements.get('error').hidden, false);
    assert.equal(f.elements.get('submit').disabled, false);
  }
});

test('partial answer shows a notice as text; complete answers hide it', async () => {
  const f = fixture(async () => response(sse(['收入123元[2]'], done({partial: true}))));
  f.elements.get('question').value = '问题'; await f.submit();
  const notice = f.part(f.assistants()[0], 'partial');
  assert.equal(notice.hidden, false);
  assert.equal(notice.textContent, '部分内容没有找到依据，请以引用原文为准。');
  assert.equal(f.elements.get('status').textContent, '回答完成');
  const g = fixture(async () => response(sse(['收入123元[2]'], done())));
  g.elements.get('question').value = '问题'; await g.submit();
  assert.equal(g.part(g.assistants()[0], 'partial').hidden, true);
});

test('page has the retention notice and loads no external script', () => {
  assert.match(html, /对话记录保存在服务器上，7 天后自动删除，请不要输入个人敏感信息/);
  assert.doesNotMatch(html, /<script[^>]+src=/i);
  assert.doesNotMatch(script, /innerHTML/);
});
