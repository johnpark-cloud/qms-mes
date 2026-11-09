from django.db import migrations

RULES = [  # (sort, name, target, pattern)
    (1, '관리표준', 'DOC', 'KEN-{관리표준 문서구분}{부서}-{일련2}'),
    (2, '양식', 'DOC', '{문서:관리표준}-{일련2}'),
    (3, '제품코드', 'ITEM', '{품목분류:1,2}{산업분류}{고객사}{일련3}'),
    (4, '원자재', 'ITEM', '{품목분류:3}{자재분류}{자재 대분류}{자재 중분류}{자재 소분류}-{일련5}'),
    (5, '기술문서', 'DOC', '{품번:제품코드}-{설계자료분류}{일련3}'),
    (6, '도면 품번', 'ITEM', '{품번:제품코드}-{설계자료분류:AS,SU,DT,PA,BA}{일련3}'),
    (7, '표준품', 'ITEM', '{품목분류:3}{품번:제품코드:뒤6}-{일련4}'),
]


def seed(apps, schema_editor):
    """추가만 한다. 이름이 이미 있으면 건너뛴다."""
    NumberRule = apps.get_model('core', 'NumberRule')
    for sort, name, target, pattern in RULES:
        NumberRule.objects.get_or_create(name=name, defaults={'target': target, 'pattern': pattern, 'sort': sort})


class Migration(migrations.Migration):

    dependencies = [('core', '0012_numberrule')]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
