"""심사 자료 출력(옛 /audit-pack/ 대신): 품번·기간으로 검사 요약·부적합·처분·CAPA·4M·관리계획서·메모를 한 장에."""
from urllib.parse import urlencode

from rest_framework.response import Response
from rest_framework.views import APIView

from qms import views as old


def _dt(v):
    return v.strftime('%Y-%m-%d %H:%M') if v else ''


def _photos(obj):
    return [p.file.url for p in obj.photos.all() if p.file]


class AuditPackView(APIView):
    schema = None

    def get(self, request):
        old._pack_allowed(request)  # 부적합·검사 보기 권한
        d = old._pack_data(request)
        item = d['item']
        out = {'items': [{'id': i.pk, 'label': f'{i.code} {i.name}'} for i in d['items']], 'errors': d['errors'],
               'from': str(d['from']), 'to': str(d['to']), 'item': None}
        if item is None:
            return Response(out)
        q = urlencode({'item': item.pk, 'from': d['from'], 'to': d['to']})
        rows = lambda xs, f: None if xs is None else [f(x) for x in xs]
        plan = d['plan']
        out.update({
            'item': {'id': item.pk, 'code': item.code, 'name': item.name}, 'limit': d['limit'], 'truncated': d['truncated'],
            'zip_url': f'/audit-pack/zip/?{q}',
            'summary': d['summary'],
            'ncs': [{'number': n.number, 'lot': n.lot.number, 'detected_at': _dt(n.detected_at), 'defect_type': n.defect_type,
                     'defect_qty': n.defect_qty, 'description': n.description, 'photos': _photos(n),
                     'disposition': n.get_disposition_display() if n.disposition else '미정',
                     'approved': f'{n.approved_by} · {_dt(n.approved_at)}' if n.approved_at else ''} for n in d['ncs']],
            'capas': rows(d['capas'], lambda c: {'number': c.number, 'text': c.title}),
            'claims': rows(d['claims'], lambda c: {'number': c.number, 'text': f'{c.customer} · {c.description}'}),
            'scars': rows(d['scars'], lambda s: {'number': s.number, 'text': f'{s.supplier} · {s.request}'}),
            'changes': rows(d['changes'], lambda c: {'number': c.number, 'category': c.get_category_display(),
                                                     'effective_at': str(c.effective_at.date()) if c.effective_at else '',
                                                     'description': c.description}),
            'can_plan': d['can_plan'],
            'plan': {'label': str(plan), 'revision': plan.revision, 'approved_at': str(plan.approved_at.date())} if plan else None,
            'plan_lines': [{'characteristic': str(l.characteristic), 'process': str(l.process or '-'), 'failure_mode': l.failure_mode,
                            'severity': l.severity, 'occurrence': l.occurrence, 'detection': l.detection, 'reaction': l.reaction}
                           for l in d['plan_lines']],
            'memos': rows(d['memos'], lambda m: {'at': _dt(m.created_at), 'author': str(m.author),
                                                 'speaker': f'{m.get_speaker_kind_display()} {m.speaker_name}'.strip(),
                                                 'body': m.body, 'photos': _photos(m)}),
        })
        return Response(out)
