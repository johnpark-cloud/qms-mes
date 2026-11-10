// 번호 규칙을 고르면 그 규칙의 칸으로 추가 화면을 다시 연다(_popup 등 다른 쿼리는 유지).
document.addEventListener('DOMContentLoaded', function () {
  var sel = document.getElementById('id_number_rule');
  if (!sel) return;
  sel.addEventListener('change', function () {
    var p = new URLSearchParams(location.search);
    if (sel.value) p.set('rule', sel.value); else p.delete('rule');
    location.search = p.toString();
  });
});
