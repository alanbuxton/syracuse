from django.shortcuts import render, redirect
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from .models import TrackedOrganization, TrackedIndustryGeo
from rest_framework.response import Response
from rest_framework import status, viewsets
from .serializers import (TrackedOrganizationSerializer,
    TrackedOrganizationModelSerializer, ActivitySerializer,
    RecentsByGeoSerializer, RecentsBySourceSerializer, CountsSerializer,
    TrackedIndustryGeoModelSerializer)
import json
from .date_helpers import days_ago
from topics.model_queries import (get_activities_for_serializer_by_country_and_date_range,
    get_cached_stats, get_activities_by_date_range_for_api,
    get_activities_for_serializer_by_source_and_date_range)
from datetime import datetime, timezone, date, timedelta
from topics.geo_utils import get_geo_data, country_and_region_code_to_name
from topics.cache_helpers import is_cache_ready

class TrackedIndustryGeoView(APIView):
    # renderer_classes = [TemplateHTMLRenderer]
    # template_name = 'preferences.html'
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication, TokenAuthentication]

    # def get_queryset(self):
    #     return TrackedIndustryGeo.objects.filter(user=self.request.user)

    def post(self, request):
        industry_name = request.data['tracked_industry_name']
        geo_code = request.data['tracked_geo_code']
        if industry_name == '':
            industry_name = None
        if geo_code == '':
            geo_code = None
        if industry_name is None and geo_code is None:
            return redirect('tracked-organizations')
        existing_industry_geos = TrackedIndustryGeo.items_by_user(self.request.user)
        if len(existing_industry_geos) <= 20 and (industry_name,geo_code) not in existing_industry_geos:
            data = {"user":self.request.user, "industry_name":industry_name,"geo_code":geo_code}
            _ = TrackedIndustryGeoModelSerializer().create(data)
        return redirect('tracked-organizations')

class TrackedOrganizationView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'preferences.html'
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication, TokenAuthentication]

    def get_queryset(self):
        return TrackedOrganization.objects.filter(user=self.request.user)

    def post(self, request, **kwargs):
        uri = request.data['tracked_organization_uri']
        existing_orgs = TrackedOrganization.uris_by_user(request.user)
        orgs_so_far = len(existing_orgs)
        if orgs_so_far <= 20 and uri not in existing_orgs:
            data = {"organization_uri":uri, "user":request.user}
            _ = TrackedOrganizationModelSerializer().create(data)
        return redirect('tracked-organizations')

    def get(self, request):
        tracked_orgs = self.get_queryset()
        tracked_org_serializer = TrackedOrganizationSerializer(tracked_orgs, many=True)
        tracked_industry_geos = TrackedIndustryGeo.print_friendly_by_user(request.user)
        source_page = request.headers.get("Referer")
        resp = Response({"tracked_orgs":tracked_org_serializer.data,"source_page":source_page,
                            "tracked_industry_geos":tracked_industry_geos,
                            "cache_ready": is_cache_ready(),
                            },status=status.HTTP_200_OK)
        return resp

class GeoActivitiesView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'tracked_activities.html'

    def get(self, request):
        min_date, max_date = min_and_max_date(request.GET)
        geo_code = request.GET.get("geo_code")
        cache_ready = is_cache_ready()
        if cache_ready:
            matching_activity_orgs = get_activities_for_serializer_by_country_and_date_range(geo_code,min_date,max_date,limit=20,include_same_as=False)
            geo_name = country_and_region_code_to_name(geo_code)
        else:
            matching_activity_orgs = []
            geo_name = ''
        serializer = ActivitySerializer(matching_activity_orgs, many=True)
        resp = Response({"activities":serializer.data,"min_date":min_date,"max_date":max_date,
                            "geo_name": geo_name,
                            "cache_ready": cache_ready,
                            }, status=status.HTTP_200_OK)
        return resp

class SourceActivitiesView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'tracked_activities.html'

    def get(self, request):
        min_date, max_date = min_and_max_date(request.GET)
        source_name = request.GET.get("source_name")
        cache_ready = is_cache_ready()
        if cache_ready:
            matching_activity_orgs =  get_activities_for_serializer_by_source_and_date_range(source_name, min_date, max_date, limit=20)
        else:
            matching_activity_orgs = []
        serializer = ActivitySerializer(matching_activity_orgs, many=True)
        resp = Response({"activities":serializer.data,"min_date":min_date,"max_date":max_date,
                            "source_name": source_name,
                            "cache_ready": cache_ready,
                             }, status=status.HTTP_200_OK)
        return resp

class GeoActivitiesViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    serializer_class = ActivitySerializer

    def get_queryset(self):
        min_date, max_date = min_and_max_date(self.request.GET)
        country_code = self.request.GET.get("geo_code")
        limit = self.request.GET.get("limit",20)
        matching_activity_orgs = get_activities_for_serializer_by_country_and_date_range(geo_code,min_date,max_date,limit=20,include_same_as=False)
        return matching_activity_orgs

class SourceActivitiesViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    serializer_class = ActivitySerializer

    def get_queryset(self):
        source_name = self.request.GET.get('source_name')
        min_date, max_date = min_and_max_date(self.request.GET)
        limit = self.request.GET.get("limit",20)
        matching_activity_orgs = get_activities_for_serializer_by_source_name_and_date_range(source_name,min_date,max_date,limit=20,include_same_as=False)
        return matching_activity_orgs


class ActivityStats(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'activity_stats.html'

    def get(self, request):
        max_date, counts, recents_by_geo, recents_by_source = get_cached_stats()
        recents_by_geo_serializer = RecentsByGeoSerializer(recents_by_geo, many=True)
        recents_by_source_serializer = RecentsBySourceSerializer(recents_by_source, many=True)
        counts_serializer = CountsSerializer(counts, many=True)
        resp = Response({"recents_by_geo":recents_by_geo_serializer.data,"counts":counts_serializer.data,
                        "recents_by_source":recents_by_source_serializer.data,
                            "max_date":max_date,
                            "cache_ready": is_cache_ready(),
                            }, status=status.HTTP_200_OK)
        return resp


class ActivitiesView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'tracked_activities.html'
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication, TokenAuthentication]

    def get(self, request):
        min_date, max_date = min_and_max_date(request.GET)
        user = request.user
        org_uris = TrackedOrganization.trackable_uris_by_user(user)
        matching_activity_orgs = get_activities_by_date_range_for_api(min_date,
                        uri_or_list=org_uris, max_date=max_date, include_same_as=True)
        serializer = ActivitySerializer(matching_activity_orgs, many=True)
        resp = Response({"activities":serializer.data,"min_date":min_date,"max_date":max_date,
                        "cache_ready": is_cache_ready(),
                        }, status=status.HTTP_200_OK)
        return resp

class ActivitiesViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    serializer_class = ActivitySerializer

    def get_queryset(self):
        uri = self.request.GET.get('uri')
        min_date = self.request.GET.get('min_date')
        results = get_activities_by_date_range_for_api(min_date,uri_or_list=[uri])
        return results


def min_and_max_date(get_params):
    min_date = get_params.get("min_date")
    if isinstance(min_date, str):
        min_date = datetime.fromisoformat(min_date)
    max_date = get_params.get("max_date",datetime.now(tz=timezone.utc))
    if isinstance(max_date, str):
        max_date = datetime.fromisoformat(max_date)
    if max_date is not None and min_date is None:
        min_date = max_date - timedelta(days=7)
    return min_date, max_date
