from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('manager', '0001_campaign_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='target',
            name='status_tag',
            field=models.CharField(
                db_index=True,
                default='pending',
                help_text='running|new_data|empty_mast|complete|error|pending',
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name='ScienceImage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('filename', models.CharField(max_length=256)),
                ('relativepath', models.CharField(blank=True, default='', max_length=512)),
                ('telescope', models.CharField(blank=True, default='', max_length=32)),
                ('instrument', models.CharField(blank=True, db_index=True, default='', max_length=32)),
                ('filter', models.CharField(blank=True, db_index=True, default='', max_length=32)),
                ('exptime', models.FloatField(blank=True, null=True)),
                ('date_obs', models.CharField(blank=True, default='', max_length=32)),
                ('ra', models.FloatField(blank=True, null=True)),
                ('dec', models.FloatField(blank=True, null=True)),
                ('size_display', models.CharField(blank=True, default='', max_length=64)),
                ('obsid', models.CharField(blank=True, default='', max_length=64)),
                ('path', models.CharField(blank=True, default='', max_length=1024)),
                (
                    'target',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='images',
                        to='manager.target',
                    ),
                ),
            ],
            options={
                'ordering': ['target_id', 'filename'],
                'unique_together': {('target', 'filename')},
            },
        ),
        migrations.CreateModel(
            name='Catalog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=256)),
                ('stem', models.CharField(max_length=256)),
                ('path', models.CharField(blank=True, default='', max_length=1024)),
                ('n_before', models.IntegerField(default=0)),
                ('n_after', models.IntegerField(default=0)),
                ('cuts_json', models.TextField(blank=True, default='')),
                (
                    'target',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='catalogs',
                        to='manager.target',
                    ),
                ),
            ],
            options={
                'ordering': ['target_id', 'stem'],
                'unique_together': {('target', 'stem')},
            },
        ),
    ]
