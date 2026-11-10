from django.urls import path
from tenders import views

urlpatterns = [
    path('api/bootstrap', views.bootstrap_view),
    path('api/profile', views.profile_view),
    path('api/profile/prefill', views.prefill_view),
    path('api/companies/search', views.company_search_view),
    path('api/tenders', views.tenders_view),
    path('api/tenders/<slug:tender_id>', views.tender_view),
    path('api/tenders/<slug:tender_id>/follow', views.follow_view),
    path('api/tenders/<slug:tender_id>/analyze', views.analyze_view),
    path('api/tenders/<slug:tender_id>/documents', views.document_upload_view),
    path('api/searches', views.searches_view),
    path('api/searches/<int:search_id>', views.search_view),
    path('api/filters/suggest', views.filter_suggestion_view),
    path('api/chat', views.chat_view),
    path('api/notifications', views.notifications_view),
    path('api/notifications/read', views.notifications_read_view),
    path('api/demo/event', views.event_view),
    path('api/demo/reset', views.reset_view),
    path('api/import', views.import_view),
    path('api/sources/pjn/sync', views.sync_view),
    path('api/documents/<slug:document_id>', views.document_view),
]
