// 웹메일(아마란스) 작성창에 붙여넣을 본문을 text/html + text/plain으로 복사한다.
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('copy-mail'), status = document.getElementById('copy-status');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const body = document.getElementById('mail-body');
    const html = body.innerHTML, text = body.innerText;  // 제목 줄은 본문 첫 단락에 들어 있다
    try {
      if (!window.ClipboardItem || !navigator.clipboard.write) {
        await navigator.clipboard.writeText(text);
        status.textContent = '글자만 복사했습니다(표 서식 없음). 웹메일 작성창에 붙여넣고 사진 ZIP을 첨부하세요.';
        return;
      }
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([html], {type: 'text/html'}),
        'text/plain': new Blob([text], {type: 'text/plain'}),
      })]);
      status.textContent = '복사했습니다. 웹메일 작성창에 붙여넣고 사진 ZIP을 첨부하세요.';
    } catch (e) {
      status.textContent = '복사하지 못했습니다. 본문을 직접 선택해 복사하세요.';
    }
  });
});
