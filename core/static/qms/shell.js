// 좁은 화면에서 사이드바 접기·펴기
document.addEventListener('click', function (e) {
    var btn = e.target.closest('.qms-side__toggle');
    if (!btn) return;
    var open = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', open);
    document.getElementById('qms-sidebar').classList.toggle('open', open);
});
