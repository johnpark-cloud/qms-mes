"""X̄-R·I-MR 관리도와 Cpk. 부분군 = 검사 1건에서 한 검사항목의 측정값들."""
from statistics import mean

E2, MR_D4, MR_d2 = 2.66, 3.267, 1.128  # I-MR 계수 (이동범위 n=2)

# 부분군 크기 n별 관리도 계수 (n=2..10)
A2 = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
D3 = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
D4 = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}
d2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}


def control_chart(subgroups, lsl=None, usl=None):
    """subgroups: [(라벨, [값...]), ...] 시간순. 크기가 모두 1이면 I-MR, 모두 같은 2~10이면 X̄-R.
    결과의 'xbar'는 I-MR에서 개별값, 'r'은 이동범위(첫 점은 None)다."""
    subgroups = [(lbl, [float(x) for x in v]) for lbl, v in subgroups]
    lsl, usl = (None if x is None else float(x) for x in (lsl, usl))
    sizes = {len(v) for _, v in subgroups}
    if len(sizes) != 1 or not 1 <= (n := sizes.pop()) <= 10:
        raise ValueError('부분군 크기가 1~10 사이로 모두 같아야 관리도를 그릴 수 있습니다.')
    if len(subgroups) < 2:
        raise ValueError('부분군이 2개 이상 필요합니다.')
    if n == 1:
        values = [v[0] for _, v in subgroups]
        points = [{'label': lbl, 'xbar': x, 'r': None if i == 0 else abs(x - values[i - 1])}
                  for i, (lbl, x) in enumerate(zip((lbl for lbl, _ in subgroups), values))]
        xbb, rbar = mean(values), mean(p['r'] for p in points[1:])
        lim = {'cl': xbb, 'ucl': xbb + E2 * rbar, 'lcl': xbb - E2 * rbar,
               'r_cl': rbar, 'r_ucl': MR_D4 * rbar, 'r_lcl': 0}
        sigma = rbar / MR_d2
    else:
        points = [{'label': lbl, 'xbar': mean(v), 'r': max(v) - min(v)} for lbl, v in subgroups]
        xbb, rbar = mean(p['xbar'] for p in points), mean(p['r'] for p in points)
        lim = {'cl': xbb, 'ucl': xbb + A2[n] * rbar, 'lcl': xbb - A2[n] * rbar,
               'r_cl': rbar, 'r_ucl': D4[n] * rbar, 'r_lcl': D3[n] * rbar}
        sigma = rbar / d2[n]
    cpk = None
    if sigma > 0 and (lsl is not None or usl is not None):
        cpk = min(x for x in ((usl - xbb) / (3 * sigma) if usl is not None else None,
                              (xbb - lsl) / (3 * sigma) if lsl is not None else None) if x is not None)
    # 이상 경보: 규칙1 관리한계 이탈, 규칙2 중심선 한쪽 연속 9점
    run, side = 0, 0
    for p in points:
        p['alarms'] = []
        if not lim['lcl'] <= p['xbar'] <= lim['ucl']:
            p['alarms'].append('관리한계 이탈')
        if p['r'] is not None and not lim['r_lcl'] <= p['r'] <= lim['r_ucl']:
            p['alarms'].append('범위(R) 이탈')
        s = (p['xbar'] > xbb) - (p['xbar'] < xbb)
        run = run + 1 if s and s == side else (1 if s else 0)
        side = s
        if run >= 9:
            p['alarms'].append('중심선 한쪽 연속 9점')
    return {'n': n, 'kind': 'I-MR' if n == 1 else 'X̄-R', 'points': points, 'limits': lim, 'sigma': sigma, 'cpk': cpk}
