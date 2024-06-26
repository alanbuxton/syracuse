from django.test import SimpleTestCase, TestCase
from topics.cache_helpers import nuke_cache
from neomodel import db
import time
import os
from datetime import datetime, timezone
from integration.models import DataImport
from integration.management.commands.import_ttl import do_import_ttl
from topics.models import Organization, Resource, Person, ActivityMixin
from integration.neo4j_utils import (
    delete_all_not_needed_resources, count_relationships,
    apoc_del_redundant_same_as,
)
from integration.rdf_post_processor import RDFPostProcessor
import logging
logger = logging.getLogger(__name__)


'''
    Care these tests will delete Neo4j DB
'''
env_var="DELETE_NEO"
if os.environ.get(env_var) != "Y":
    print(f"Set env var {env_var}=Y to confirm you want to drop Neo4j database")
    exit(0)

def count_relevant_nodes():
    query = """MATCH (n: Resource) WHERE SIZE(LABELS(n)) > 1
                OR n.uri CONTAINS 'https://sws.geonames.org'
                RETURN COUNT(n);""" # Resource + at least one other label, or Geoname
    val, _ = db.cypher_query(query)
    return val[0][0]

def clean_db():
    db.cypher_query("MATCH (n) CALL {WITH n DETACH DELETE n} IN TRANSACTIONS OF 10000 ROWS;")
    DataImport.objects.all().delete()

def clean_db_and_load_files(dirname,do_post_processing=False):
    clean_db()
    assert DataImport.latest_import() == None # Empty DB
    do_import_ttl(dirname=dirname,force=True,do_archiving=False,do_post_processing=do_post_processing)
    delete_all_not_needed_resources() # Lots of "sameAs" entries that aren't available in any test data
    apoc_del_redundant_same_as()

class TurtleLoadingTestCase(TestCase):

    def test_loads_ttl_files(self):
        clean_db_and_load_files("integration/test_dump/dump-3")
        assert len(DataImport.objects.all()) == 2
        assert DataImport.latest_import() == 20231224180800

    def test_reloads_ttl_files(self):
        clean_db_and_load_files("integration/test_dump/dump-1",do_post_processing=True)
        node_count = count_relevant_nodes()
        assert node_count == 1809
        latest_import = DataImport.objects.all()[0]
        assert latest_import.deletions == 0
        assert latest_import.creations > 0 and latest_import.creations <= node_count
        
        # TODO re-implement delete & recreate logic
        # node_will_be_deleted_and_reinstated = "https://1145.am/db/4076092/Sauber_Group"
        # node_will_be_deleted = "https://1145.am/db/4076564/Oldcastle_Buildingenvelope"
        #
        # do_import_ttl(dirname="integration/test_dump/dump-1.5",force=True,do_archiving=False,do_post_processing=True)
        #
        # do_import_ttl(dirname="integration/test_dump/dump-2",force=True,do_archiving=False,do_post_processing=True)
        # delete_all_not_needed_resources()
        # node_count2 = count_relevant_nodes()
        # assert node_count2 == node_count - 1

class MergeSameAsHighTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        clean_db()
        nuke_cache() # Company name etc are stored in cache
        org_nodes = [make_node(x,y) for x,y in zip(range(100,200),"abcdefghijk")]
        act_nodes = [make_node(x,y,"CorporateFinanceActivity") for x,y in zip(range(100,200),"mnopqrs")]
        node_list = ", ".join(org_nodes + act_nodes)
        query = f"""
            CREATE {node_list},
            (a)<-[:sameAsHigh]-(b),
            (b)-[:sameAsHigh]->(c),
            (c)-[:sameAsHigh]->(d),
            (e)-[:sameAsHigh]->(f),
            (f)<-[:sameAsHigh]-(g),
            (g)-[:sameAsHigh]->(a),

            (h)-[:sameAsHigh]->(i),
            (i)-[:sameAsHigh]->(j),
            (i)<-[:sameAsHigh]-(k),

            (a)-[:buyer]->(m),
            (b)-[:buyer]->(n),
            (c)-[:buyer]->(o),
            (d)-[:investor]->(p),
            (e)-[:investor]->(q),
            (f)-[:buyer]->(r),
            (g)-[:buyer]->(s),

            (m)-[:target]->(h),
            (n)-[:target]->(i),
            (o)-[:target]->(j),
            (p)-[:target]->(k),
            (q)-[:target]->(h),
            (r)-[:target]->(i),
            (s)-[:target]->(j)
        """
        res,_ = db.cypher_query(query)
        R = RDFPostProcessor()
        a = Organization.nodes.get_or_none(uri="https://1145.am/db/100/a")
        assert len(a.buyer) == 1
        assert len(a.investor) == 0
        assert len(a.vendor) == 0
        R.merge_same_as_high_connections()

    def test_merges_all_same_as_highs(self):
        target_uris = []
        merged_uris = []
        for x, y in zip("abcdefghijk",range(100,200)):
            uri = f"https://1145.am/db/{y}/{x}"
            if x in "ah": # target merged nodes
                target_uris.append(uri)
            else:
                merged_uris.append(uri)
        for uri in target_uris:
            logger.info(uri)
            assert Organization.unmerged_or_none_by_uri(uri) is not None
        for uri in merged_uris:
            logger.info(uri)
            assert Organization.nodes.get_or_none(uri=uri) is not None
            assert Organization.unmerged_or_none_by_uri(uri) is None

    def test_attributes_for_ultimate_target(self):
        a = Organization.self_or_ultimate_target_node("https://1145.am/db/100/a")
        assert a.best_name == 'Name A'
        assert a.industry_as_str == 'Baz, Bar'

    def test_gets_ultimate_target(self):
        o = Organization.self_or_ultimate_target_node("https://1145.am/db/105/f")
        assert o.uri == "https://1145.am/db/100/a"
        assert o.best_name == 'Name A'

    def test_merges_connections1(self):
        a = Organization.self_or_ultimate_target_node("https://1145.am/db/101/b") # Actually a
        assert a.uri == "https://1145.am/db/100/a"
        assert len(a.buyer) == 5
        assert len(a.investor) == 2
        assert len(a.vendor) == 0

    def test_merges_connections2(self):
        h = Organization.self_or_ultimate_target_node("https://1145.am/db/109/j") # Actually h
        assert len(h.target) == 7

def clear_neo():
    db.cypher_query("MATCH (n) CALL {WITH n DETACH DELETE n} IN TRANSACTIONS OF 10000 ROWS;")


def make_node(doc_id,letter,node_type="Organization",doc_extract=None,datestamp=datetime.now(tz=timezone.utc)):
    if node_type == "Organization":
        industry = "bar" if letter in "aeiou" else "baz"
        industry_str = f"industry: ['{industry}'],"
    else:
        industry_str = ""
    if "Activity" in node_type:
        status_str = "status: ['some status'], "
    else:
        status_str = ""

    node = f"({letter}:Resource:{node_type} {{uri: 'https://1145.am/db/{doc_id}/{letter}', name: ['Name {letter.upper()}'], {industry_str} {status_str} internalDocId: {doc_id}}})"
    if doc_extract is None:
        doc_extract_text = ''
    else:
        doc_extract = doc_extract.replace("'","")
        doc_extract_text = f"documentExtract: '{doc_extract}''"
    doc_source = f"""(docsource_{letter}:Resource:Article {{uri: 'https://1145.am/db/article_{letter}',
                        headline: 'Headline {letter}', sourceOrganization:'Foo', datePublished: datetime('{datestamp.isoformat()}') }})"""
    doc_extract_str = ""
    if "Activity" in node_type:
        doc_extract_str = f"{{ documentExtract: 'Doc Extract {letter.upper()}' }}"
    return f"{node}-[:documentSource {doc_extract_str}]->{doc_source}, (docsource_{letter})-[:url]->(ext_{letter}:Resource {{ uri: 'https://example.org/external/art_{letter}' }})"
