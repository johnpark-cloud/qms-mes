import json
import os
import urllib.request

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from qms.due import digest, due_items


class Command(BaseCommand):
    help = '기한 초과·임박 항목을 회사 메일(QMS_NOTIFY_EMAILS)과 Teams(QMS_TEAMS_WEBHOOK)로 보낸다. 보낼 것이 없으면 보내지 않는다.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='보내지 않고 내용만 출력')

    def handle(self, dry_run, **opts):
        groups = digest(due_items(approver=True))
        if not groups:
            self.stdout.write('보낼 항목이 없습니다.')
            return
        title = f'[QMS] {timezone.localdate():%Y-%m-%d} 기한·대기 항목 {sum(len(l) for _, l in groups)}건'
        body = '\n\n'.join(f'■ {t}\n' + '\n'.join(f'- {x}' for x in lines) for t, lines in groups)
        if dry_run:
            self.stdout.write(f'{title}\n\n{body}')
            return
        emails = [e.strip() for e in os.environ.get('QMS_NOTIFY_EMAILS', '').split(',') if e.strip()]
        webhook = os.environ.get('QMS_TEAMS_WEBHOOK', '')
        if not emails and not webhook:
            raise CommandError('QMS_NOTIFY_EMAILS 또는 QMS_TEAMS_WEBHOOK 환경변수를 지정하세요.')
        if emails:
            send_mail(title, body, None, emails)
            self.stdout.write(f'메일 발송: {", ".join(emails)}')
        if webhook:
            post_teams(webhook, title, groups)
            self.stdout.write('Teams 발송')


def post_teams(url, title, groups):
    """Teams 워크플로·수신 웹후크 모두 받는 Adaptive Card 메시지."""
    body = [{'type': 'TextBlock', 'text': title, 'weight': 'Bolder', 'size': 'Medium', 'wrap': True}]
    for t, lines in groups:
        body.append({'type': 'TextBlock', 'text': t, 'weight': 'Bolder', 'spacing': 'Medium', 'wrap': True})
        body.append({'type': 'TextBlock', 'text': '\n'.join(f'- {x}' for x in lines), 'wrap': True})
    payload = {'type': 'message', 'attachments': [{
        'contentType': 'application/vnd.microsoft.card.adaptive',
        'content': {'$schema': 'http://adaptivecards.io/schemas/adaptive-card.json', 'type': 'AdaptiveCard',
                    'version': '1.4', 'body': body}}]}
    req = urllib.request.Request(url, json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status >= 300:
            raise CommandError(f'Teams 응답 {r.status}')
