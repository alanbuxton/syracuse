from django.test import TestCase
import time
from django.contrib.auth import get_user_model
from trackeditems.serializers import TrackedOrganizationModelSerializer
from trackeditems.models import TrackedOrganization, ActivityNotification
from django.db.utils import IntegrityError
from datetime import datetime, timezone
from trackeditems.notification_helpers import prepare_recent_changes_email_notification_by_max_date
from neomodel import db
from integration.models import DataImport
from topics.cache_helpers import nuke_cache, warm_up_cache
from integration.management.commands.import_ttl import do_import_ttl
import re
import os

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
        assert DataImport.latest_import() == None # Empty DB
        nuke_cache()
        do_import_ttl(dirname="dump",force=True,do_archiving=False)

    def setUp(self):
        self.ts = time.time()
        self.user = get_user_model().objects.create(username=f"test-{self.ts}")
        to1 = TrackedOrganization.objects.create(user=self.user, organization_uri="https://1145.am/db/2139377/Shawbrook") # 2023-10-08
        to2 = TrackedOrganization.objects.create(user=self.user, organization_uri="https://1145.am/db/2657106/Nokia") # 2007-03-27T00:00:00Z
        to3 = TrackedOrganization.objects.create(user=self.user, organization_uri="https://1145.am/db/2138009/Bioenterprise_Canada") # 2023-10-05

    def test_creates_activity_notification_for_first_time_user(self):
        ActivityNotification.objects.filter(user=self.user).delete()
        max_date = datetime(2023,10,9,tzinfo=timezone.utc)
        email, activity_notif = prepare_recent_changes_email_notification_by_max_date(self.user,max_date,7)
        assert activity_notif.num_activities == 5
        assert len(re.findall(r"\bNokia\b",email)) == 1
        assert len(re.findall(r"\bBioenterprise Canada\b",email)) == 13
        assert len(re.findall(r"\bShawbrook\b",email)) == 5
        assert "Oct. 9, 2023" in email
        assert "Oct. 2, 2023" in email

    def test_creates_activity_notification_for_user_with_existing_notifications(self):
        ActivityNotification.objects.filter(user=self.user).delete()
        ActivityNotification.objects.create(user=self.user,
                max_date=datetime(2023,10,7,tzinfo=timezone.utc),num_activities=2,sent_at=datetime(2023,10,7,tzinfo=timezone.utc))
        max_date = datetime(2023,10,9,tzinfo=timezone.utc)
        email, activity_notif = prepare_recent_changes_email_notification_by_max_date(self.user,max_date,7)
        assert activity_notif.num_activities == 1
        assert len(re.findall(r"\bNokia\b",email)) == 1
        assert len(re.findall(r"\bBioenterprise Canada\b",email)) == 1
        assert len(re.findall(r"\bShawbrook\b",email)) == 5
        assert "Oct. 9, 2023" in email
        assert "Oct. 7, 2023" in email
        assert "Oct. 2, 2023" not in email

    def test_only_populates_activity_pages_if_cache_available(self):
        nuke_cache()
        response = self.client.get("/tracked/activity_stats")
        content = str(response.content)
        assert "Site stats calculating, please check later" in content
        assert "Showing updates as at" not in content
        response = self.client.get("/tracked/geo_activities?geo_code=US-CA&max_date=2023-10-07")
        assert "Activities between" not in content
        assert "Click on a document title to see the original source" not in content
        assert "Site stats calculating, please check later" in content
        assert "Machina Labs Secures" not in content
        assert "Pow.Bio announced" not in content
        response = self.client.get("/tracked/source_activities?source_name=Associated%20Press&max_date=2023-10-07")
        assert "Activities between" not in content
        assert "Click on a document title to see the original source" not in content
        assert "Site stats calculating, please check later" in content
        assert "The Humane Society of Southern Arizona" not in content
        assert "Gluckstadt Police Department" not in content
        warm_up_cache()
        response = self.client.get("/tracked/activity_stats")
        content = str(response.content)
        assert "Site stats calculating, please check later" not in content
        assert "Showing updates as at" in content
        response = self.client.get("/tracked/geo_activities?geo_code=US-CA&max_date=2023-10-07")
        content = str(response.content)
        assert "Activities between" in content
        assert "Click on a document title to see the original source" in content
        assert "Site stats calculating, please check later" not in content
        assert "Machina Labs Secures" in content
        assert "Pow.Bio announced" in content
        response = self.client.get("/tracked/source_activities?source_name=Associated%20Press&max_date=2023-10-07")
        content = str(response.content)
        assert "Activities between" in content
        assert "Click on a document title to see the original source" in content
        assert "Site stats calculating, please check later" not in content
        assert "The Humane Society of Southern Arizona" in content
        assert "Gluckstadt Police Department" in content
