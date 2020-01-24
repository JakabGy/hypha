# Generated by Django 2.2.9 on 2020-01-24 11:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('utils', '0003_add_site_logo_setting'),
    ]

    operations = [
        migrations.AlterField(
            model_name='socialmediasettings',
            name='site_name',
            field=models.CharField(blank=True, default='opentech', help_text='Site name, used by Open Graph.', max_length=255),
        ),
    ]
