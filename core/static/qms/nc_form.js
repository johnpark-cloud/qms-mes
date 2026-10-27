// 부적합 발생 유형에 맞는 칸만 보인다 (유형이 읽기 전용이면 모두 보인다)
document.addEventListener('DOMContentLoaded', function () {
    var origin = document.getElementById('id_origin');
    if (!origin) return;
    var rules = [
        ['.nc-incoming', ['INCOMING']],
        ['.field-process', ['PROCESS', 'OUTGOING']],
        ['.field-customer_notify, .field-customer_notified_on', ['CLAIM', 'RETURN', 'OUTGOING']]
    ];
    function apply() {
        rules.forEach(function (r) {
            document.querySelectorAll(r[0]).forEach(function (el) {
                el.style.display = r[1].indexOf(origin.value) < 0 ? 'none' : '';
            });
        });
    }
    origin.addEventListener('change', apply);
    apply();
});
