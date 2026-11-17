from django.db import migrations

OLD, NEW = '고객 특별 요구사항', '고객 특정 요구사항'


def rename(old, new):
    def run(apps, schema_editor):
        # 17번 요소 이름만 바꾼다. 사용자가 고친 다른 이름은 건드리지 않는다.
        apps.get_model('qms', 'PpapElement').objects.filter(number=17, name=old).update(name=new)
    return run


class Migration(migrations.Migration):
    dependencies = [('qms', '0012_terms_iso')]
    operations = [migrations.RunPython(rename(OLD, NEW), rename(NEW, OLD))]
