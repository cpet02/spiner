from django.db import models


class LibraryEntry(models.Model):
    """A book the user confirmed into their library -- either an
    auto-confirmed high-confidence match or one they picked/corrected
    during the review step. No FK to a catalog row: the catalog is a
    flat CSV loaded at runtime, not a DB table, so we snapshot the
    fields we need at confirmation time instead."""
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=300, blank=True, default="")
    isbn = models.CharField(max_length=20, blank=True, default="")
    match_score = models.FloatField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]

    def __str__(self):
        return f"{self.title} — {self.author}"
