from django.shortcuts import render
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from topics.models import Organization, ActivityMixin
from .serializers import (OrganizationGraphSerializer, OrganizationSerializer,
    NameSearchSerializer, GeoSerializer, TimelineSerializer,
    IndustrySearchSerializer,OrganizationTimelineSerializer)
from rest_framework import status
from datetime import date
from .geo_utils import COUNTRY_NAMES, COUNTRY_CODES
from urllib.parse import urlparse
from syracuse.settings import MOTD, REQUIRE_END_USER_LOGIN
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
import json

class AuthAPIView(APIView):
    if REQUIRE_END_USER_LOGIN:
        permission_classes = [IsAuthenticated]
        authentication_classes = [SessionAuthentication, TokenAuthentication]

class Index(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'index.html'

    def get(self,request):
        params = request.query_params
        org_name = params.get("name")
        country = params.get("selected_country")
        if org_name:
            orgs = Organization.find_by_name(org_name)
            org_list = OrganizationSerializer(orgs, many=True)
            org_search = NameSearchSerializer({"name":org_name})
            geo_serializer = GeoSerializer(choices=COUNTRY_NAMES)
            search_type = 'org_name'
            num_hits = len(orgs)
            search_term = org_name
        elif country:
            orgs = Organization.based_in_country(country)
            orgs_by_activity = ActivityMixin.orgs_by_activity_where(country)
            all_orgs = set(orgs + orgs_by_activity)
            org_list = OrganizationSerializer(all_orgs, many=True)
            org_search = NameSearchSerializer({"name":""})
            geo_serializer = GeoSerializer(choices=COUNTRY_NAMES,initial=country)
            search_type = 'country'
            search_term = COUNTRY_CODES[country]
            num_hits = len(all_orgs)
        else:
            orgs = Organization.nodes.order_by('?')[:10]
            org_list = OrganizationSerializer(orgs, many=True)
            org_search = NameSearchSerializer({"name":org_name})
            geo_serializer = GeoSerializer(choices=COUNTRY_NAMES)
            search_type = 'random'
            search_term = None
            num_hits = 0
        orgs_to_show = org_list.data
        if len(orgs_to_show) > 20:
            orgs_to_show = orgs_to_show[:20]
        industry_serializer = IndustrySearchSerializer()

        show_lists = False
        if (not REQUIRE_END_USER_LOGIN) or request.user.is_authenticated:
            show_lists = True

        alpha_flag = request.GET.get("alpha_flag")

        resp = Response({"organizations":orgs_to_show,
                        "search_serializer": org_search,
                        "selected_country": geo_serializer,
                        "search_term": search_term,
                        "num_hits": num_hits,
                        "industry_serializer": industry_serializer,
                        "search_type": search_type,
                        "motd": MOTD,
                        "show_lists": show_lists,
                        "alpha_flag": alpha_flag,
                        "show_login": REQUIRE_END_USER_LOGIN}, status=status.HTTP_200_OK)
        return resp

class TopicsTimeline(AuthAPIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'topics_timeline.html'

    def get(self, request):
        params = request.query_params
        industry = params["industry_name"]
        orgs = Organization.find_by_industry(industry)
        timeline_serializer = TimelineSerializer(orgs)
        return Response({"industry_name":industry,"timeline_serializer": timeline_serializer.data}, status=status.HTTP_200_OK)

class OrganizationTimeline(AuthAPIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'organization_timeline.html'

    def get(self, request, *args, **kwargs):
        uri = f"https://{kwargs['domain']}/{kwargs['path']}/{kwargs['doc_id']}/{kwargs['name']}"
        o = Organization.nodes.get(uri=uri)
        org_serializer = OrganizationTimelineSerializer(o)
        org_data = {**kwargs, **{"uri":o.uri,"source_node_name":o.longest_name}}
        resp = Response({"timeline_serializer": org_serializer.data,
                            "org_data":org_data}, status=status.HTTP_200_OK)
        return resp


class RandomOrganization(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'organization_linkages.html'

    def get(self, request):
        o = Organization.get_random()
        vals = elements_from_uri(o.uri)
        org_serializer = OrganizationGraphSerializer(o)
        resp = Response({"data_serializer": org_serializer.data,
                            "org_data":vals}, status=status.HTTP_200_OK)
        return resp


class OrganizationByUri(AuthAPIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'organization_linkages.html'

    if REQUIRE_END_USER_LOGIN:
        permission_classes = [IsAuthenticated]
        authentication_classes = [SessionAuthentication, TokenAuthentication]

    def get(self, request, *args, **kwargs):
        uri = f"https://{kwargs['domain']}/{kwargs['path']}/{kwargs['doc_id']}/{kwargs['name']}"
        o = Organization.nodes.get(uri=uri)
        include_where = request.GET.get("include_where","false").lower() == "true"
        org_serializer = OrganizationGraphSerializer(o, context={"include_where":include_where})
        org_data = {**kwargs, **{"uri":o.uri,"source_node_name":o.longest_name}}
        resp = Response({"data_serializer": org_serializer.data,
                            "org_data":org_data,
                            "where_is_included": include_where}, status=status.HTTP_200_OK)
        return resp


def elements_from_uri(uri):
    parsed = urlparse(uri)
    part_pieces = parsed.path.split("/")
    path = part_pieces[1]
    doc_id = part_pieces[2]
    org_name = "/".join(part_pieces[3:])
    return {
        "domain": parsed.netloc,
        "path": path,
        "doc_id": doc_id,
        "name": org_name,
    }
