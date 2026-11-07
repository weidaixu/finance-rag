// Offline checks for the actual inline page script; uses Node's built-in APIs only.
// Run: node --test web/client.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

class Element {
  constructor(text = '') {
    this.children = []; this.attributes = {}; this.listeners = {}; this.dataset = {};
    this.hidden = false; this.disabled = false; this.value = ''; this._text = text;
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
}

function fixture(fetch) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const examples = [new Element('提问示例')];
  const context = vm.createContext({
    document: {getElementById: id => elements.get(id), querySelectorAll: () => examples,
      createElement: () => new Element(), createTextNode: text => new Element(text)},
    fetch, TextDecoder, Uint8Array, AbortController, setTimeout, clearTimeout,
  });
  vm.runInContext(script, context);
  return {elements, context, submit: () => elements.get('ask-form').listeners.submit({preventDefault() {}})};
}

const done = (overrides = {}) => ({answer: '收入123元[2]', refused: false, refusal_reason: '', error: '',
  citations: [{n: 2, doc_id: 'test-report', title: '测试财报', page: 6, section: '财务数据', kind: 'table', text: '收入123元'}],
  unverified_numbers: [], usage: {input_tokens: 12, output_tokens: 34, cost_yuan: .0001}, ...overrides});
function sse(parts, final, newline = '\n') {
  return [...parts.map(text => ['token', {text}]), ['done', final]].map(([kind, data]) =>
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
  assert.equal(f.elements.get('answer').textContent, '收入123元[2]');
  assert.equal(f.elements.get('status').textContent, '回答完成');
  assert.match(f.elements.get('usage').textContent, /输入 12 Token.*输出 34 Token/);
  const citation = f.elements.get('answer').children.find(el => el.className === 'citation');
  assert.equal(citation.textContent, '[2]'); citation.listeners.click();
  assert.equal(f.elements.get('source-title').textContent, '测试财报');
  assert.match(f.elements.get('source-meta').textContent, /PDF 第 6 页/);
  assert.equal(f.elements.get('pdf-link').href, '/api/pdf/test-report#page=6');
  assert.equal(f.elements.get('submit').disabled, false);
});

test('final refusal replaces provisional text and removes citations', async () => {
  const f = fixture(async () => response(sse(['暂时显示的错误回答'], done({refused: true, refusal_reason: 'no_valid_citation', answer: ''}))));
  f.elements.get('question').value = '营业收入'; await f.submit();
  assert.doesNotMatch(f.elements.get('answer').textContent, /暂时显示/);
  assert.match(f.elements.get('answer').textContent, /缺少有效引用/);
  assert.equal(f.elements.get('source-list').hidden, true);
});

test('untrusted answer and source stay text and unverified numbers produce a warning', async () => {
  const attack = '<img src=x onerror=alert(1)>';
  const data = done({answer: attack + '[2]', unverified_numbers: ['9999'],
    citations: [{n: 2, doc_id: 'report /中', title: attack, page: 7, section: attack, text: attack, kind: 'text'}]});
  const f = fixture(async () => response(sse([attack], data)));
  f.elements.get('question').value = '问题'; await f.submit();
  assert.equal(f.elements.get('answer').textContent, attack + '[2]');
  assert.equal(f.elements.get('source-text').textContent, attack);
  assert.equal(f.elements.get('source-title').textContent, attack);
  assert.equal(f.elements.get('pdf-link').href, '/api/pdf/report%20%2F%E4%B8%AD#page=7');
  assert.equal(f.elements.get('warning').hidden, false);
  assert.match(f.elements.get('warning').textContent, /9999/);
});

test('done error clears provisional content without displaying raw error', async () => {
  const f = fixture(async () => response(sse(['未完成内容'], done({error: 'sk-secret F:/private'}))));
  f.elements.get('question').value = '问题'; await f.submit();
  assert.equal(f.elements.get('answer').textContent, '');
  assert.equal(f.elements.get('error').textContent, '回答生成失败，请稍后重试。');
});

test('missing done or malformed JSON rejects provisional answer and unlocks submit', async () => {
  for (const body of ['event: token\ndata: {"text":"不完整"}\n\n', 'event: done\ndata: invalid\n\n']) {
    const f = fixture(async () => response(body)); f.elements.get('question').value = '问题'; await f.submit();
    assert.equal(f.elements.get('answer').textContent, '');
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
  f.elements.get('question').value = '  问题  ';
  const pending = f.submit();
  assert.equal(f.elements.get('submit').disabled, true);
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
