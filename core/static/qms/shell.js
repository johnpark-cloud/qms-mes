// 뒤로가기·앞으로가기로 메모리에 남은 예전 화면(bfcache)이 복원되면 서버에서 최신 내용을 다시 받는다
window.addEventListener('pageshow', function (e) {
    if (e.persisted) location.reload();
});

// 좁은 화면에서 사이드바 접기·펴기
document.addEventListener('click', function (e) {
    var btn = e.target.closest('.qms-side__toggle');
    if (!btn) return;
    var open = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', open);
    document.getElementById('qms-sidebar').classList.toggle('open', open);
});

// 사이드바 묶음 접기·펴기: 사용자가 펴거나 접은 묶음을 이 브라우저에 기억한다. 지금 화면의 묶음은 항상 펼친다
(function () {
    var KEY = 'qms.nav.open', saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { saved = {}; }
    document.querySelectorAll('.qms-nav-group').forEach(function (d) {
        var name = d.dataset.group;
        if (!d.hasAttribute('data-active') && name in saved) d.open = saved[name];
        d.addEventListener('toggle', function () {
            saved[name] = d.open;
            try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) { /* 저장 못 해도 화면은 그대로 동작 */ }
        });
    });
})();

// 통합 검색: Ctrl+K로 이동, 결과가 있으면 aria-expanded, 아래 화살표로 결과 이동, Esc로 닫기
document.addEventListener('keydown', function (e) {
    var input = document.getElementById('shell-search-input');
    if (!input) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); input.focus(); input.select(); }
    else if (e.key === 'Escape' && document.activeElement.closest('.shell-search')) {
        document.getElementById('search-results').innerHTML = ''; input.focus();
    } else if (e.key === 'ArrowDown' && document.activeElement === input) {
        var a = document.querySelector('#search-results a');
        if (a) { e.preventDefault(); a.focus(); }
    }
});
document.addEventListener('htmx:afterSwap', function (e) {
    if (e.target.id !== 'search-results') return;
    document.getElementById('shell-search-input').setAttribute('aria-expanded', e.target.querySelector('a') ? 'true' : 'false');
});
