from django.urls import path

from . import views

urlpatterns = [
    path('scan/', views.scan_shelf, name='scan-shelf'),
    path('library/', views.LibraryListCreate.as_view(), name='library-list-create'),
]
