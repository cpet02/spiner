from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import pipeline
from .models import LibraryEntry
from .serializers import LibraryEntrySerializer


@api_view(['POST'])
def scan_shelf(request):
    """Accept an uploaded shelf photo, run the full detect -> read -> match
    pipeline, and return its result dict as-is -- pipeline.run_pipeline()
    already resolves every failure mode (no detections, VLM errors,
    unreadable spines) into the "books" list rather than raising."""
    upload = request.FILES.get('image')
    if upload is None:
        return Response({"error": "missing 'image' file field"}, status=400)

    result = pipeline.run_pipeline(upload.read())
    return Response(result)


class LibraryListCreate(generics.ListCreateAPIView):
    """GET lists the user's confirmed library, newest first. POST adds one
    entry -- called when the app confirms an auto-match or the user
    resolves a review-step item (confirm/correct). Discarded books never
    reach this endpoint."""
    queryset = LibraryEntry.objects.all()
    serializer_class = LibraryEntrySerializer
