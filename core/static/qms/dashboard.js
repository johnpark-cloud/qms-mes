// 첫 화면 위젯 배치 편집. 배치는 서버(사용자별)에 저장해 다른 PC에서도 같게 보인다.
// 넓은 화면은 4칸 × 10줄 격자: 위젯마다 칸(x, y)을 갖고, 보통은 1×1, 넓게는 2×2를 차지한다.
const COLS = 4, ROWS = 10;
const span = size => size === 'wide' ? 2 : 1;
const byPos = (a, b) => a.y - b.y || a.x - b.x;

// qms/widgets.py의 place와 같은 규칙: 목록 순서대로, 지정 칸이 비어 있으면 그대로, 아니면 위→아래·왼→오른쪽 첫 빈자리.
// 넓게 놓을 자리가 없으면 보통으로 줄이고, 그래도 없으면 뺀다.
function place(items) {
  const taken = new Set(), out = [];
  const cells = (x, y, n) => { const c = []; for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) c.push(`${x + i},${y + j}`); return c; };
  const isFree = (x, y, n) => cells(x, y, n).every(c => !taken.has(c));
  const firstFree = n => {
    for (let y = 0; y <= ROWS - n; y++) for (let x = 0; x <= COLS - n; x++) if (isFree(x, y, n)) return [x, y];
    return null;
  };
  for (const it of items) {
    let size = it.size, n = span(size), spot = null;
    if (Number.isInteger(it.x) && Number.isInteger(it.y)) {
      const x = Math.min(Math.max(it.x, 0), COLS - n), y = Math.min(Math.max(it.y, 0), ROWS - n);
      if (isFree(x, y, n)) spot = [x, y];
    }
    spot = spot || firstFree(n);
    if (!spot && n === 2) { size = 'normal'; n = 1; spot = firstFree(1); }
    if (!spot) continue;
    cells(spot[0], spot[1], n).forEach(c => taken.add(c));
    out.push({...it, size, x: spot[0], y: spot[1]});
  }
  return out.sort(byPos);
}

document.addEventListener('DOMContentLoaded', () => {
  const dash = document.getElementById('dash'), toggle = document.getElementById('dash-edit');
  if (!dash || !toggle) return;
  const add = document.getElementById('dash-add'), status = document.getElementById('dash-status');
  const csrf = document.querySelector('.dash-tools [name=csrfmiddlewaretoken]').value;
  const grid = matchMedia('(min-width: 1100px)');  // fiori.css의 4칸 격자 구간
  const widgets = () => [...dash.querySelectorAll('.widget')];
  const editing = () => document.body.classList.contains('dash-editing');
  const items = () => widgets().map(el => ({el, key: el.dataset.key, size: el.dataset.size,
                                            x: parseInt(el.dataset.x, 10), y: parseInt(el.dataset.y, 10)}));
  const name = el => el.querySelector('.widget__name').textContent;
  let dragged = null, grab = {x: 0, y: 0};

  // 자리를 다시 잡아 화면에 반영한다. 빈칸이 모자라 빠지거나 줄어드는 위젯이 생기면 아무것도 바꾸지 않는다.
  const relayout = order => {
    const out = place(order);
    if (out.length < order.length || out.some(o => o.size !== o.el.dataset.size)) {
      status.textContent = '빈칸이 모자랍니다. 다른 위젯을 줄이거나 삭제하세요.';
      return false;
    }
    for (const o of out) {
      Object.assign(o.el.dataset, {x: o.x, y: o.y});
      o.el.style.setProperty('--col', o.x + 1);
      o.el.style.setProperty('--row', o.y + 1);
      dash.append(o.el);  // 좁은 화면은 문서 순서대로 흐르므로 (y, x) 순으로 다시 늘어놓는다
    }
    return true;
  };
  const moveTo = (el, x, y) => {
    const all = items(), me = all.find(i => i.el === el);
    Object.assign(me, {x, y});
    const focused = document.activeElement === el;
    if (relayout([me, ...all.filter(i => i !== me).sort(byPos)])) {
      status.textContent = `${name(el)}: ${+el.dataset.y + 1}줄 ${+el.dataset.x + 1}칸`;
    }
    if (focused) el.focus();  // 다시 늘어놓아도 키보드 초점 유지
  };

  const refreshAdd = () => {
    const placed = new Set(widgets().map(w => w.dataset.key));
    for (const o of add.options) if (o.value) o.hidden = o.disabled = placed.has(o.value);
  };
  const setEditing = on => {
    document.body.classList.toggle('dash-editing', on);
    toggle.setAttribute('aria-pressed', on);
    widgets().forEach(w => { w.draggable = on; on ? w.tabIndex = 0 : w.removeAttribute('tabindex'); });
    if (on && !dash.querySelector('.dash__cell')) {  // 놓을 수 있는 칸을 흐리게 보여 준다 (넓은 화면만, CSS)
      const cells = document.createDocumentFragment();
      for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
        const c = document.createElement('div');
        c.className = 'dash__cell';
        c.dataset.x = x; c.dataset.y = y;
        c.style.setProperty('--col', x + 1);
        c.style.setProperty('--row', y + 1);
        cells.append(c);
      }
      dash.prepend(cells);  // 위젯보다 앞에 두어 위젯 아래에 그려지게
    }
    refreshAdd();
  };
  toggle.addEventListener('click', () => setEditing(toggle.getAttribute('aria-pressed') !== 'true'));

  dash.addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const w = btn.closest('.widget');
    if (btn.dataset.act === 'size') {
      const before = w.dataset.size, wide = before !== 'wide';
      w.dataset.size = wide ? 'wide' : 'normal';
      const all = items(), me = all.find(i => i.el === w);
      if (relayout([me, ...all.filter(i => i !== me).sort(byPos)])) {  // 제자리에서 커지고 겹친 위젯이 비켜 간다
        w.classList.toggle('widget--wide', wide);
        btn.textContent = wide ? '보통' : '넓게';
        status.textContent = '크기를 바꿨습니다. 저장하면 내용이 다시 표시됩니다.';
      } else {
        w.dataset.size = before;
      }
      btn.focus();
    }
    if (btn.dataset.act === 'remove') {
      w.remove();
      refreshAdd();
      status.textContent = '삭제했습니다. 저장해야 반영됩니다.';
      toggle.focus();
    }
  });

  add.addEventListener('change', () => {
    const opt = add.selectedOptions[0];
    if (!opt.value) return;
    const w = document.getElementById('dash-new').content.firstElementChild.cloneNode(true);
    w.dataset.key = opt.value;
    w.draggable = true;
    w.tabIndex = 0;
    w.setAttribute('aria-label', `${opt.textContent} 위젯`);
    w.querySelector('.widget__name').textContent = w.querySelector('h2').textContent = opt.textContent;
    dash.append(w);
    add.value = '';
    if (!relayout(items().sort((a, b) => (a.el === w) - (b.el === w) || byPos(a, b)))) {  // 새 위젯은 첫 빈칸으로
      w.remove();
      return;
    }
    refreshAdd();
    status.textContent = `${opt.textContent} 위젯을 추가했습니다. 저장하면 내용이 표시됩니다.`;
  });

  // 끌어 놓기: 넓은 화면은 놓은 위치의 칸, 좁은 화면은 놓은 위젯의 칸으로 옮긴다.
  const cellAt = e => {
    const r = dash.getBoundingClientRect(), cs = getComputedStyle(dash);
    const gap = parseFloat(cs.columnGap) || 0, rowH = parseFloat(cs.gridAutoRows) || 1;
    const colW = (r.width - gap * (COLS - 1)) / COLS;
    return {x: Math.round((e.clientX - grab.x - r.left) / (colW + gap)), y: Math.round((e.clientY - grab.y - r.top) / (rowH + gap))};
  };
  const target = e => {
    if (grid.matches) return cellAt(e);
    const t = e.target.closest('.widget');
    return t && t !== dragged ? {x: +t.dataset.x, y: +t.dataset.y} : null;
  };
  const mark = e => {
    const t = e && grid.matches ? target(e) : null, n = dragged ? span(dragged.dataset.size) : 1;
    dash.querySelectorAll('.dash__cell').forEach(c => {
      const dx = c.dataset.x - (t ? Math.min(Math.max(t.x, 0), COLS - n) : -9), dy = c.dataset.y - (t ? Math.min(Math.max(t.y, 0), ROWS - n) : -9);
      c.classList.toggle('is-target', dx >= 0 && dx < n && dy >= 0 && dy < n);
    });
  };
  dash.addEventListener('dragstart', e => {
    if (!editing()) return;
    dragged = e.target.closest('.widget');
    if (!dragged) return;
    const r = dragged.getBoundingClientRect();
    grab = {x: e.clientX - r.left, y: e.clientY - r.top};
    dragged.classList.add('is-dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragged.dataset.key);  // Firefox는 데이터가 있어야 끌기를 시작한다
  });
  dash.addEventListener('dragover', e => { if (dragged) { e.preventDefault(); mark(e); } });
  dash.addEventListener('drop', e => {
    e.preventDefault();
    const t = dragged && target(e);
    if (t) moveTo(dragged, t.x, t.y);
  });
  dash.addEventListener('dragend', () => {
    if (dragged) dragged.classList.remove('is-dragging');
    dragged = null;
    mark(null);
  });

  // 키보드: 편집 중 위젯을 선택하고 방향키로 한 칸씩 옮긴다.
  const keys = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
  dash.addEventListener('keydown', e => {
    const w = e.target;
    if (!editing() || !w.classList.contains('widget') || !keys[e.key]) return;
    e.preventDefault();
    const [dx, dy] = keys[e.key];
    moveTo(w, +w.dataset.x + dx, +w.dataset.y + dy);
  });

  const save = async items => {
    try {
      const r = await fetch(dash.dataset.saveUrl, {
        method: 'POST', body: JSON.stringify(items),
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      });
      if (r.ok) return location.reload();
    } catch (e) { /* 아래 안내로 처리 */ }
    status.textContent = '저장하지 못했습니다. 다시 시도하세요.';
  };
  document.getElementById('dash-save').addEventListener('click', () =>
    save(items().sort(byPos).map(({key, size, x, y}) => ({key, size, x, y}))));
  document.getElementById('dash-reset').addEventListener('click', () => {
    if (confirm('기본 배치로 되돌릴까요? 저장한 배치는 지워집니다.')) save([]);
  });
});
