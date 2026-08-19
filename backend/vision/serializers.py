from rest_framework import serializers

from .models import LibraryEntry


class LibraryEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LibraryEntry
        fields = ["id", "title", "author", "isbn", "match_score", "added_at"]
        read_only_fields = ["id", "added_at"]
