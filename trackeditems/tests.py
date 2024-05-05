from django.test import TestCase
import time
from django.contrib.auth import get_user_model
from trackeditems.serializers import TrackedOrganizationModelSerializer
from trackeditems.models import TrackedOrganization, ActivityNotification, TrackedIndustryGeo
from django.db.utils import IntegrityError
from datetime import datetime, timezone
from trackeditems.notification_helpers import (
    prepare_recent_changes_email_notification_by_max_date,
    make_email_notif_from_orgs
)
from neomodel import db
from integration.models import DataImport
from topics.cache_helpers import nuke_cache, warm_up_cache
from integration.management.commands.import_ttl import do_import_ttl
import re
import os
from integration.neo4j_utils import delete_all_not_needed_resources
from topics.models import Article, CorporateFinanceActivity
from topics.model_queries import activity_articles_to_api_results
from integration.rdf_post_processor import RDFPostProcessor

'''
    Care these tests will delete neodb data
'''
env_var="DELETE_NEO"
if os.environ.get(env_var) != "Y":
    print(f"Set env var {env_var}=Y to confirm you want to drop Neo4j database")
    exit(0)


class TrackedOrganizationSerializerTestCase(TestCase):

    def setUp(self):
        self.ts = time.time()
        self.user = get_user_model().objects.create(username=f"test-{self.ts}")

    def test_does_not_create_duplicates(self):
        org_uri = f"https://foo.example.org/testorg2-{self.ts}"
        to1 = TrackedOrganizationModelSerializer().create({"user":self.user,"organization_uri":org_uri})
        matching_orgs = TrackedOrganization.objects.filter(user=self.user)
        assert len(matching_orgs) == 1
        assert matching_orgs[0].organization_uri == org_uri
        with self.assertRaises(IntegrityError):
            to2 = TrackedOrganizationModelSerializer().create({"user":self.user,"organization_uri":org_uri.upper()})

class ActivityTestsWithSampleDataTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        db.cypher_query("MATCH (n) CALL {WITH n DETACH DELETE n} IN TRANSACTIONS OF 10000 ROWS;")
        DataImport.objects.all().delete()
        assert DataImport.latest_import() is None # Empty DB
        nuke_cache()
        do_import_ttl(dirname="dump",force=True,do_archiving=False,do_post_processing=False)
        delete_all_not_needed_resources()
        r = RDFPostProcessor()
        r.run_all_in_order()
        warm_up_cache()

    def setUp(self):
        self.ts = time.time()
        self.user = get_user_model().objects.create(username=f"test-{self.ts}")
        to1 = TrackedOrganization.objects.create(user=self.user, organization_uri="https://1145.am/db/4075273/Openai")
        to2 = TrackedOrganization.objects.create(user=self.user, organization_uri="https://1145.am/db/4074438/Titan_Pro_Technologies") # 2007-03-27T00:00:00Z
        to3 = TrackedOrganization.objects.create(user=self.user, organization_uri="https://1145.am/db/4076678/Bioaffinity_Technologies") # 2023-10-05
        self.ts2 = time.time()
        self.user2 = get_user_model().objects.create(username=f"test-{self.ts2}")
        tig1 = TrackedIndustryGeo.objects.create(user=self.user2,
                                        industry_name="Pharmaceutical, Pharmaceuticals, Drug, Drugs",
                                        geo_code="US")
        tig2 = TrackedIndustryGeo.objects.create(user=self.user2,
                                        industry_name="Tech, Technology, Hightech, Engineering",
                                        geo_code="SG")
        tig3 = TrackedIndustryGeo.objects.create(user=self.user2,
                                        industry_name="Analytics, Enterprise, Insights, Data",
                                        geo_code="")
        tig4 = TrackedIndustryGeo.objects.create(user=self.user2,
                                        industry_name="",
                                        geo_code="AU")

    def test_finds_merged_uris_for_tracked_orgs(self):
        tracked_orgs = TrackedOrganization.by_user(self.user)
        org_uris = [x.organization_uri for x in tracked_orgs]
        assert set(org_uris) == set(['https://1145.am/db/4075273/Openai',
                                'https://1145.am/db/4074438/Titan_Pro_Technologies',
                                'https://1145.am/db/4076678/Bioaffinity_Technologies'])
        org_or_merged_uris = [x.organization_or_merged_uri for x in tracked_orgs]
        assert set(org_or_merged_uris) == set(['https://1145.am/db/4074766/Openai', # Different one
                                'https://1145.am/db/4074438/Titan_Pro_Technologies',
                                'https://1145.am/db/4076678/Bioaffinity_Technologies'])

    def test_writes_and_x_more_when_more_than_limit(self):
        activity_uri = "https://1145.am/db/4076003/Avoamerica_Peru_Acquisition"
        article_uri = "https://1145.am/db/wwwreuterscom_markets_deals_abu-dhabi-owned-unifrutti-eyes-further-latam-growth-after-fresh-acquisitions-2024-03-09_"
        article = Article.nodes.get_or_none(uri=article_uri)
        activity = CorporateFinanceActivity.nodes.get_or_none(uri=activity_uri)
        activity_articles = [(activity,article),]
        matching_activity_orgs = activity_articles_to_api_results(activity_articles)
        email,_ = make_email_notif_from_orgs(matching_activity_orgs,[],[],None,None,None)
        assert len(re.findall("and 1 more",email)) == 2
        assert len(re.findall("and 2 more",email)) == 1

    def test_creates_activity_notification_for_first_time_user(self):
        ActivityNotification.objects.filter(user=self.user).delete()
        max_date = datetime(2024,3,11,tzinfo=timezone.utc)
        email_and_activity_notif = prepare_recent_changes_email_notification_by_max_date(self.user,max_date,7)
        email, activity_notif = email_and_activity_notif
        assert len(re.findall(r"\bTitan Pro Technologies\b",email)) == 4
        assert len(re.findall(r"\bbioAffinity Technologies\b",email)) == 4
        assert len(re.findall(r"\bOpenAI\b",email)) == 33
        assert "March 11, 2024" in email
        assert "March 4, 2024" in email
        assert activity_notif.num_activities == 10
        assert len(re.findall("https://web.archive.org/20240309235959/",email)) == 10
        assert len(re.findall("https://web.archive.org/20240309\*/",email)) == 10
        assert "https://www.theglobeandmail.com/world/article-openai-has-full-confidence-in-ceo-sam-altman-after-investigation/" in email
        assert "None" not in email

    def test_creates_activity_notification_for_user_with_existing_notifications(self):
        ActivityNotification.objects.filter(user=self.user).delete()
        ActivityNotification.objects.create(user=self.user,
                max_date=datetime(2024,3,9,tzinfo=timezone.utc),num_activities=2,sent_at=datetime(2024,3,9,tzinfo=timezone.utc))
        max_date = datetime(2024,3,11,tzinfo=timezone.utc)
        email_and_activity_notif = prepare_recent_changes_email_notification_by_max_date(self.user,max_date,7)
        assert email_and_activity_notif is not None
        email, activity_notif = email_and_activity_notif
        assert len(re.findall(r"\bTitan Pro Technologies\b",email)) == 1
        assert len(re.findall(r"\bbioAffinity Technologies\b",email)) == 1
        assert len(re.findall(r"\bOpenAI\b",email)) == 25
        assert "March 11, 2024" in email
        assert "March 4, 2024" not in email
        assert "March 9, 2024" in email
        assert activity_notif.num_activities == 6

    def test_creates_geo_industry_notification_for_new_user(self):
        ActivityNotification.objects.filter(user=self.user2).delete()
        max_date = datetime(2024,3,11,tzinfo=timezone.utc)
        email_and_activity_notif = prepare_recent_changes_email_notification_by_max_date(self.user2,max_date,7)
        email, activity_notif = email_and_activity_notif
        assert "<b>Pharmaceutical, Pharmaceuticals, Drug, Drugs</b> in the <b>United States</b>" in email
        assert "We are not tracking any specific organizations for you." in email
        assert activity_notif.num_activities == 19
        assert len(re.findall("RenovoRx",email)) == 16
        assert len(re.findall("Ryde Group Ltd",email)) == 3
        assert len(re.findall(r"Industry:.+Technology",email)) == 1
        assert len(re.findall(r"Industry:.+Biopharm",email)) == 4
        assert len(re.findall(r"Region:.+Singapore",email)) == 2
        assert len(re.findall(r"Region.+United States",email)) == 3
        assert len(re.findall(r"Industry:.+Tech",email)) == 16
        assert len(re.findall("OpenAI",email)) == 44
        assert len(re.findall("MC Mining",email)) == 3
        assert "None" not in email

    def test_only_populates_activity_pages_if_cache_available(self):
        ''' For testing
            from django.test import Client
            client = Client()
        '''
        client = self.client
        nuke_cache()

        response = client.get("/tracked/activity_stats")
        content = str(response.content)
        assert "Site stats calculating, please check later" in content
        assert "Showing updates as at" not in content

        response = client.get("/tracked/geo_activities?geo_code=US-CA&max_date=2024-03-10")
        content = str(response.content)
        assert "Activities between" not in content
        assert "Click on a document link to see the original source document" not in content
        assert "Site stats calculating, please check later" in content
        assert "Sonendo " not in content

        response = client.get("/tracked/source_activities?source_name=Associated%20Press&max_date=2024-03-10")
        content = str(response.content)
        assert "Activities between" not in content
        assert "Click on a document link to see the original source document" not in content
        assert "Site stats calculating, please check later" in content
        assert "Los Angeles Rams" not in content

        warm_up_cache()
        response = client.get("/tracked/activity_stats")
        content = str(response.content)
        assert "Site stats calculating, please check later" not in content
        assert "Showing updates as at" in content

        response = client.get("/tracked/geo_activities?geo_code=US-CA&max_date=2024-03-10")
        content = str(response.content)
        assert "Activities between" in content
        assert "Site stats calculating, please check later" not in content
        assert "Sonendo " in content

        response = client.get("/tracked/source_activities?source_name=Associated%20Press&max_date=2024-03-10")
        content = str(response.content)
        assert "Activities between" in content
        assert "Click on a document link to see the original source document" in content
        assert "Site stats calculating, please check later" not in content
        assert "Los Angeles Rams" in content
