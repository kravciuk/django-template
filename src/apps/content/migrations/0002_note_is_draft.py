from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='note',
            name='is_draft',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
