"""측정시스템 분석(MSA) GR&R 계산: AIAG MSA 평균·범위법. 원자료는 한 줄에 측정 1회(부품·측정자·반복·측정값)."""
import math

from django.core.exceptions import ValidationError

COLUMNS = ('부품', '측정자', '반복', '측정값')
K1 = {2: 0.8862, 3: 0.5908}  # 반복 횟수
K2 = {2: 0.7071, 3: 0.5231}  # 측정자 수
K3 = {2: 0.7071, 3: 0.5231, 4: 0.4467, 5: 0.4030, 6: 0.3742, 7: 0.3534, 8: 0.3375, 9: 0.3249, 10: 0.3146}  # 부품 수
GUIDE = ('GR&R 원자료(CSV·엑셀): 첫 줄 열 제목 부품·측정자·반복·측정값, 한 줄에 측정 1회. '
         '부품 2~10개, 측정자 2~3명, 반복 2~3회, 모든 부품·측정자가 같은 횟수.')


def _mean(xs):
    return sum(xs) / len(xs)


def grr(rows):
    """rows: {열 제목: 값} 목록 → EV·AV·GRR·PV·TV·%GRR·ndc. 틀이 맞지 않으면 ValidationError."""
    cells = {}
    for n, r in enumerate(rows, start=2):
        if any(c not in r for c in COLUMNS):
            raise ValidationError(f'열 제목이 {"·".join(COLUMNS)}이어야 합니다.')
        try:
            v = float(r['측정값'])
        except (TypeError, ValueError):
            raise ValidationError(f'{n}행: 측정값 「{r["측정값"]}」이(가) 숫자가 아닙니다.')
        cells.setdefault((str(r['부품']), str(r['측정자'])), []).append(v)
    parts = sorted({p for p, _ in cells})
    ops = sorted({o for _, o in cells})
    trials = {len(v) for v in cells.values()}
    if len(ops) not in K2:
        raise ValidationError(f'측정자는 2~3명이어야 합니다(지금 {len(ops)}명).')
    if len(parts) not in K3:
        raise ValidationError(f'부품은 2~10개여야 합니다(지금 {len(parts)}개).')
    if len(trials) != 1 or len(cells) != len(parts) * len(ops) or trials.pop() not in K1:
        raise ValidationError('모든 부품·측정자의 반복 횟수가 같아야 하고 2~3회여야 합니다.')
    r = len(next(iter(cells.values())))
    ev = _mean([max(v) - min(v) for v in cells.values()]) * K1[r]
    op_means = [_mean([x for (p, o), v in cells.items() if o == op for x in v]) for op in ops]
    av2 = ((max(op_means) - min(op_means)) * K2[len(ops)]) ** 2 - ev ** 2 / (len(parts) * r)
    av = math.sqrt(av2) if av2 > 0 else 0
    part_means = [_mean([x for (p, o), v in cells.items() if p == part for x in v]) for part in parts]
    pv = (max(part_means) - min(part_means)) * K3[len(parts)]
    g = math.hypot(ev, av)
    tv = math.hypot(g, pv)
    if not tv or not g:
        raise ValidationError('측정값에 변동이 없어 계산할 수 없습니다.')
    return {'ev': ev, 'av': av, 'grr': g, 'pv': pv, 'tv': tv, 'grr_percent': round(100 * g / tv, 2),
            'ndc': int(1.41 * pv / g), 'parts': len(parts), 'operators': len(ops), 'trials': r}


def judge(grr_percent, ndc):
    """AIAG: %GRR 10 이하 적합, 30 이하 조건부, 그 밖 부적합. 구별 범주(ndc) 5 미만도 부적합."""
    from .models import MsaStudy
    if ndc < 5 or grr_percent > 30:
        return MsaStudy.REJECT
    return MsaStudy.ACCEPT if grr_percent <= 10 else MsaStudy.CONDITIONAL


def summary(r, tolerance=None):
    text = (f"평균·범위법, 부품 {r['parts']} × 측정자 {r['operators']} × 반복 {r['trials']}. "
            f"EV {r['ev']:.5g}, AV {r['av']:.5g}, GRR {r['grr']:.5g}, PV {r['pv']:.5g}, TV {r['tv']:.5g}")
    if tolerance:
        text += f", 공차 대비 %GRR {100 * 6 * r['grr'] / float(tolerance):.2f}"
    return text


def from_file(uploaded):
    """업로드 파일(들여오기와 같은 읽기) → grr 결과. 읽은 뒤 처음으로 되감아 파일 전체가 저장되게 한다."""
    from core.importer import read_rows
    try:
        rows = [row for _, row in read_rows(uploaded, 1)]
    except Exception:  # 깨진 파일·다른 형식
        raise ValidationError('CSV 또는 엑셀(.xlsx) 파일을 읽지 못했습니다.')
    finally:
        uploaded.seek(0)
    return grr(rows)
