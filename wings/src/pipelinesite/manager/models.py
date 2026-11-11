"""Campaign index models for program / target / stage metadata."""

from __future__ import annotations

from django.db import models


class Program(models.Model):
    program_id = models.CharField(max_length=16, unique=True, db_index=True)
    short_name = models.CharField(max_length=64)
    title = models.CharField(max_length=512)
    pi = models.CharField(max_length=128, blank=True, default='')
    institution = models.CharField(max_length=256, blank=True, default='')
    cycle = models.CharField(max_length=32, blank=True, default='')
    orbits = models.CharField(max_length=32, blank=True, default='')
    status = models.CharField(max_length=64, blank=True, default='')
    url = models.URLField(blank=True, default='')
    output_name = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        ordering = ['program_id']

    def __str__(self) -> str:
        return self.short_name or self.program_id


class Target(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='targets')
    name = models.SlugField(max_length=64, unique=True, db_index=True)
    display_name = models.CharField(max_length=128)
    host = models.CharField(max_length=128, blank=True, default='', db_index=True)
    field_role = models.CharField(max_length=16, default='prime')
    sn_type = models.CharField(max_length=32, blank=True, default='')
    ra = models.FloatField()
    dec = models.FloatField()
    ra_sex = models.CharField(max_length=32, blank=True, default='')
    dec_sex = models.CharField(max_length=32, blank=True, default='')
    radius_arcmin = models.FloatField(default=5.0)
    instruments = models.CharField(max_length=128, blank=True, default='')
    telescope = models.CharField(max_length=16, default='hst')
    base_dir = models.CharField(max_length=512)
    notes = models.TextField(blank=True, default='')
    n_images = models.IntegerField(default=0)
    job_state = models.CharField(max_length=32, default='pending', db_index=True)
    new_data = models.BooleanField(default=False)
    n_new_obs = models.IntegerField(default=0)
    distance_mpc = models.FloatField(null=True, blank=True)
    distance_err_mpc = models.FloatField(null=True, blank=True)
    distance_catalog = models.CharField(max_length=64, blank=True, default='')
    distance_display = models.CharField(max_length=64, blank=True, default='')
    redshift = models.FloatField(null=True, blank=True)
    has_catalog = models.BooleanField(default=False)
    has_reference = models.BooleanField(default=False)
    status_tag = models.CharField(
        max_length=32,
        default='pending',
        db_index=True,
        help_text='running|new_data|empty_mast|complete|error|pending',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.display_name or self.name


class StageRun(models.Model):
    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='stages')
    key = models.CharField(max_length=32)
    state = models.CharField(max_length=16, default='pending')
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    seconds = models.FloatField(null=True, blank=True)
    log = models.CharField(max_length=512, blank=True, default='')

    class Meta:
        unique_together = ('target', 'key')
        ordering = ['target_id', 'key']

    def __str__(self) -> str:
        return f'{self.target.name}:{self.key}={self.state}'


class ScienceImage(models.Model):
    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='images')
    filename = models.CharField(max_length=256)
    relativepath = models.CharField(max_length=512, blank=True, default='')
    telescope = models.CharField(max_length=32, blank=True, default='')
    instrument = models.CharField(max_length=32, blank=True, default='', db_index=True)
    filter = models.CharField(max_length=32, blank=True, default='', db_index=True)
    exptime = models.FloatField(null=True, blank=True)
    date_obs = models.CharField(max_length=32, blank=True, default='')
    ra = models.FloatField(null=True, blank=True)
    dec = models.FloatField(null=True, blank=True)
    size_display = models.CharField(max_length=64, blank=True, default='')
    obsid = models.CharField(max_length=64, blank=True, default='')
    path = models.CharField(max_length=1024, blank=True, default='')

    class Meta:
        unique_together = ('target', 'filename')
        ordering = ['target_id', 'filename']

    def __str__(self) -> str:
        return self.filename


class Catalog(models.Model):
    target = models.ForeignKey(Target, on_delete=models.CASCADE, related_name='catalogs')
    name = models.CharField(max_length=256)
    stem = models.CharField(max_length=256)
    path = models.CharField(max_length=1024, blank=True, default='')
    n_before = models.IntegerField(default=0)
    n_after = models.IntegerField(default=0)
    cuts_json = models.TextField(blank=True, default='')

    class Meta:
        unique_together = ('target', 'stem')
        ordering = ['target_id', 'stem']

    def __str__(self) -> str:
        return self.name
