from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import pipeline


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
