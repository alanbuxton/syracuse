from django.db import models
from datetime import datetime, timezone

class DataImport(models.Model):

    run_at = models.DateTimeField()
    import_ts = models.TextField()
    deletions = models.IntegerField()
    creations = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint("run_at", "import_ts", name="unique_run_import_ts")
        ]
        ordering = ['-run_at','-import_ts']

    @staticmethod
    def latest_import():
        res = DataImport.objects.order_by("-import_ts")
        if len(res) == 0:
            return None
        ts = res[0].import_ts
        return int(ts)

    @staticmethod
    def latest_import_ts():
        ts = DataImport.latest_import()
        fmt = "%Y%m%d%H%M%S"
        d = datetime.strptime(str(ts),fmt)
        return d.astimezone(timezone.utc)    
