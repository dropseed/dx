# Generated by Plain 0.20.0 on 2025-02-05 19:32

import plain.models.deletion
from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="NotFoundLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True)),
                ("url", models.URLField()),
                ("ip_address", models.GenericIPAddressField()),
                ("user_agent", models.CharField(max_length=255)),
                ("referer", models.URLField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Redirect",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True)),
                ("from_pattern", models.CharField(max_length=255)),
                ("to_pattern", models.CharField(max_length=255)),
                ("http_status", models.IntegerField(default=301)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("order", models.IntegerField(default=0)),
            ],
            options={
                "ordering": ["order", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="RedirectLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True)),
                ("ip_address", models.GenericIPAddressField()),
                ("user_agent", models.CharField(max_length=255)),
                ("referer", models.URLField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("from_url", models.URLField()),
                ("to_url", models.URLField()),
                ("http_status", models.IntegerField(default=301)),
                (
                    "redirect",
                    models.ForeignKey(
                        on_delete=plain.models.deletion.CASCADE,
                        to="plainredirection.redirect",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
