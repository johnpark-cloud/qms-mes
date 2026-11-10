// 번호 규칙을 고르면 그 규칙의 칸으로 추가 화면을 다시 연다.
document.addEventListener('DOMContentLoaded', function () {
  var sel = document.getElementById('id_number_rule');
  if (sel) sel.addEventListener('change', function () { location.search = '?rule=' + encodeURIComponent(sel.value); });
});
