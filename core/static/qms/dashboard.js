// 첫 화면 위젯 배치 편집. 배치는 서버(사용자별)에 저장해 다른 PC에서도 같게 보인다.
document.addEventListener('DOMContentLoaded', () => {
  const dash = document.getElementById('dash'), toggle = document.getElementById('dash-edit');
  if (!dash || !toggle) return;
  const add = document.getElementById('dash-add'), status = document.getElementById('dash-status');
  const csrf = document.querySelector('.dash-tools [name=csrfmiddlewaretoken]').value;
  const widgets = () => [...dash.querySelectorAll('.widget')];
  let dragged = null;

  const refreshAdd = () => {
    const placed = new Set(widgets().map(w => w.dataset.key));
    for (const o of add.options) if (o.value) o.hidden = o.disabled = placed.has(o.value);
  };
  const setEditing = on => {
    document.body.classList.toggle('dash-editing', on);
    toggle.setAttribute('aria-pressed', on);
    widgets().forEach(w => { w.draggable = on; });
    refreshAdd();
  };
  toggle.addEventListener('click', () => setEditing(toggle.getAttribute('aria-pressed') !== 'true'));

  dash.addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const w = btn.closest('.widget');
    if (btn.dataset.act === 'up' && w.previousElementSibling) w.previousElementSibling.before(w);
    if (btn.dataset.act === 'down' && w.nextElementSibling) w.nextElementSibling.after(w);
    if (btn.dataset.act === 'size') {
      const wide = w.dataset.size !== 'wide';
      w.dataset.size = wide ? 'wide' : 'normal';
      w.classList.toggle('widget--wide', wide);
      btn.textContent = wide ? '보통' : '넓게';
    }
    if (btn.dataset.act === 'remove') {
      w.remove();
      refreshAdd();
      status.textContent = '삭제했습니다. 저장해야 반영됩니다.';
      toggle.focus();
      return;
    }
    btn.focus();  // 옮긴 뒤에도 키보드 초점을 같은 버튼에 둔다
  });

  add.addEventListener('change', () => {
    const opt = add.selectedOptions[0];
    if (!opt.value) return;
    const w = document.getElementById('dash-new').content.firstElementChild.cloneNode(true);
    w.dataset.key = opt.value;
    w.draggable = true;
    w.querySelector('.widget__name').textContent = w.querySelector('h2').textContent = opt.textContent;
    dash.append(w);
    add.value = '';
    refreshAdd();
    status.textContent = `${opt.textContent} 위젯을 추가했습니다. 저장하면 내용이 표시됩니다.`;
  });

  dash.addEventListener('dragstart', e => {
    if (!document.body.classList.contains('dash-editing')) return;
    dragged = e.target.closest('.widget');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragged.dataset.key);  // Firefox는 데이터가 있어야 끌기를 시작한다
  });
  dash.addEventListener('dragover', e => { if (dragged) e.preventDefault(); });
  dash.addEventListener('drop', e => {
    e.preventDefault();
    const target = e.target.closest('.widget');
    if (dragged && target && target !== dragged) {
      const all = widgets();
      all.indexOf(dragged) < all.indexOf(target) ? target.after(dragged) : target.before(dragged);
    }
  });
  dash.addEventListener('dragend', () => { dragged = null; });

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
    save(widgets().map(w => ({key: w.dataset.key, size: w.dataset.size}))));
  document.getElementById('dash-reset').addEventListener('click', () => {
    if (confirm('기본 배치로 되돌릴까요? 저장한 배치는 지워집니다.')) save([]);
  });
});
