from django.urls import path, register_converter
from topics import views
from .converters import DateConverter

register_converter(DateConverter, 'date')

urlpatterns = [
    path('', views.Index.as_view(), name='index'),
    path('random-organization', views.RandomOrganization.as_view(), name='random-organization'),
    path('organization/linkages/uri/<str:domain>/<str:path>/<doc_id>/<str:name>', views.OrganizationByUri.as_view(), name='organization-linkages'),
    path('organization/timeline/uri/<str:domain>/<str:path>/<doc_id>/<str:name>', views.OrganizationTimeline.as_view(), name='organization-timeline'),
    path('organization/family-tree/uri/<str:domain>/<str:path>/<doc_id>/<str:name>', views.FamilyTree.as_view(), name='organization-family-tree'),
    path('timeline', views.TopicsTimeline.as_view(), name="timeline"),
    path('about', views.About.as_view(), name="about"),
    path('resource/<str:domain>/<str:path>/<doc_id>/<str:name>', views.ShowResource.as_view(), name='resource-with-doc-id'),
    path('resource/<str:domain>/<str:path>/<str:name>', views.ShowResource.as_view(), name='resource-no-doc-id'),
]
