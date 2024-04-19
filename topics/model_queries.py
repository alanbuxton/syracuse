from neomodel import db
from .models import Organization, ActivityMixin, IndustryCluster, Article, CorporateFinanceActivity
from .geo_utils import get_geoname_uris_for_country_region
from datetime import datetime, timezone, timedelta
from typing import List, Union
import logging
from django.core.cache import cache
from topics.geo_utils import geo_select_list

logger = logging.getLogger(__name__)

def get_activities_for_serializer_by_country_and_date_range(geo_code,min_date,max_date,limit=20,include_same_as=True):
    relevant_uris = get_relevant_org_uris_for_country_region_industry(geo_code,limit=None)
    matching_activity_orgs = get_activities_by_date_range_for_api(min_date, uri_or_list=relevant_uris,
                                max_date=max_date, limit=limit, include_same_as=include_same_as)
    return matching_activity_orgs

def get_activities_for_serializer_by_source_and_date_range(source_name, min_date, max_date, limit=20):
    matching_activity_orgs = get_activities_by_date_range_for_api(min_date, source_name=source_name,
                                max_date=max_date, limit=limit, include_same_as=False)
    return matching_activity_orgs

def get_relevant_org_uris_for_country_region_industry(geo_code, industry_id=None, limit=20):
    all_orgs=get_relevant_orgs_for_country_region_industry(geo_code, industry_id, limit)
    uris = [x.uri for x in all_orgs]
    return uris

def get_relevant_orgs_for_country_region_industry(geo_code,industry_id=None,limit=20):
    cache_key = f"relevant_orgs_{geo_code}_{industry_id}_{limit}"
    logger.info(f"Checking Geo Code: {geo_code} Industry ID: {industry_id}")
    res = cache.get(cache_key)
    if res is not None:
        return res
    industry_uris = IndustryCluster.with_descendants(industry_id)
    ts1 = datetime.utcnow()
    orgs = Organization.by_country_region_industry(geo_code,industry_uris,limit=limit,allowed_to_set_cache=True)
    ts2 = datetime.utcnow()
    orgs_by_activity = ActivityMixin.orgs_by_activity_where_industry(geo_code,industry_uris,limit=limit)
    ts3 = datetime.utcnow()
    logger.info(f"{geo_code} orgs took: {ts2 - ts1}; orgs by act took: {ts3 - ts2}")
    all_orgs = set(orgs + orgs_by_activity)
    cache.set(cache_key, all_orgs)
    return all_orgs


def get_activities_by_date_range_for_api(min_date, uri_or_list: Union[str,List[str],None] = None,
                                            source_name: Union[str,None] = None,
                                            max_date = datetime.now(tz=timezone.utc),
                                            limit = None, include_same_as=True):
    assert min_date is not None, "Must have min date"
    assert min_date <= max_date,  f"Min date {min_date} must be before or same as max date {max_date}"
    if (uri_or_list is None or len(uri_or_list) == 0 or set(uri_or_list) == {None}) and source_name is None:
        return []
    if source_name is None:
        activity_articles = get_activities_by_org_uri_and_date_range(uri_or_list, min_date, max_date, limit,include_same_as)
    else:
        activity_articles = get_activities_by_source_and_date_range(source_name, min_date, max_date, limit, include_same_as)
    return activity_articles_to_api_results(activity_articles)

def get_activities_by_date_range_industry_geo_for_api(min_date, max_date,geo_code,industry_id):
    if industry_id is None:
        allowed_org_uris = None
    else:
        industry_uris = IndustryCluster.with_descendants(industry_id)
        industry_orgs = Organization.by_country_region_industry(geo_code=None,
                            industry_uris=industry_uris,limit=None,allowed_to_set_cache=True)
        allowed_org_uris = [x.uri for x in industry_orgs]
    geo_uris = get_geoname_uris_for_country_region(geo_code)
    query = build_get_activities_by_date_range_industry_geo_query(min_date, max_date, allowed_org_uris, geo_uris)
    objs, _ = db.cypher_query(query, resolve_objects=True)
    return activity_articles_to_api_results(objs)


def build_get_activities_by_date_range_industry_geo_query(min_date, max_date, allowed_org_uris, geo_uris):
    if geo_uris is None:
        geo_clause = ''
    else:
        geo_clause = f"""AND (EXISTS {{ MATCH (x)-[:whereGeoNameRDF]-(loc:Resource) WHERE loc.uri IN {geo_uris} }}
                        OR EXISTS {{ MATCH (o)-[:basedInHighGeoNameRDF]-(loc:Resource) WHERE loc.uri in {geo_uris} }})"""
    if allowed_org_uris is None:
        org_uri_clause = ''
    else:
        org_uri_clause = f"AND o.uri IN {allowed_org_uris}"
    query = f"""
        MATCH (a: Article)<-[:documentSource]-(x: CorporateFinanceActivity|LocationActivity)--(o: Organization)
        WHERE a.datePublished >= datetime('{date_to_cypher_friendly(min_date)}')
        AND a.datePublished <= datetime('{date_to_cypher_friendly(max_date)}')
        {org_uri_clause}
        {geo_clause}
        RETURN x,a
        UNION
        MATCH (a: Article)<-[:documentSource]-(x: RoleActivity)--(p: Role)--(o: Organization)
        WHERE a.datePublished >= datetime('{date_to_cypher_friendly(min_date)}')
        AND a.datePublished <= datetime('{date_to_cypher_friendly(max_date)}')
        {org_uri_clause}
        {geo_clause}
        RETURN x,a
    """
    return query

def activity_articles_to_api_results(activity_articles):
    api_results = []
    for activity,article in activity_articles:
        assert isinstance(activity, ActivityMixin), f"{activity} should be an Activity"
        api_row = {}
        api_row["source_organization"] = article.sourceOrganization
        api_row["date_published"] = article.datePublished
        api_row["headline"] = article.headline
        api_row["document_extract"] = activity.documentSource.relationship(article).documentExtract
        api_row["document_url"] = article.documentURL
        api_row["archive_org_page_url"] = article.archiveOrgPageURL
        api_row["archive_org_list_url"] = article.archiveOrgListURL
        api_row["activity_uri"] = activity.uri
        api_row["activity_where"] = activity.whereGeoName_as_str
        api_row["activity_class"] = activity.__class__.__name__
        api_row["activity_types"] = activity.activityType
        api_row["activity_longest_type"] = activity.longest_activityType
        api_row["activity_statuses"] = activity.status
        api_row["activity_status_as_string"] = activity.status_as_string
        participants = {}
        for participant_role, participant in activity.all_participants.items():
            if participant is not None and participant != []:
                if participants.get(participant_role) is None:
                    participants[participant_role] = set()
                participants[participant_role].update(participant)
        api_row["participants"] = participants
        api_results.append(api_row)
    return api_results

def get_all_source_names():
    sources, _ = db.cypher_query("MATCH (n:Article) RETURN DISTINCT n.sourceOrganization;")
    flattened = [x for sublist in sources for x in sublist]
    return flattened

def get_activities_by_source_and_date_range(source_name,min_date, max_date, limit=None,counts_only=False):
    query = build_get_activities_by_source_and_date_range_query(source_name,min_date, max_date, limit,counts_only)
    objs, _ = db.cypher_query(query, resolve_objects=True)
    return objs[:limit]

def build_get_activities_by_source_and_date_range_query(source_name,min_date, max_date, limit,counts_only):
    if counts_only is True:
        return_str = "RETURN COUNT(DISTINCT(n))"
    else:
        return_str = "RETURN n,a ORDER BY a.publishDate DESC"
    if limit is not None:
        limit_str = f"LIMIT {limit}"
    else:
        limit_str = ""
    where_clause = f"""WHERE a.datePublished >= datetime('{date_to_cypher_friendly(min_date)}')
                    AND a.datePublished <= datetime('{date_to_cypher_friendly(max_date)}')
                    AND a.sourceOrganization = ('{source_name}')"""

    query = f"""MATCH (n:CorporateFinanceActivity|LocationActivity)-[:documentSource]->(a:Article)
                {where_clause}
                {return_str} {limit_str}
                UNION
                MATCH (a: Article)<-[:documentSource]-(n:RoleActivity)--(p: Role)--(o: Organization)
                {where_clause}
                {return_str} {limit_str};"""
    return query

def get_activities_by_org_uri_and_date_range(uri_or_uri_list: Union[str,List], min_date,
                        max_date, limit=None, include_same_as=True, counts_only = False):
    query=build_get_activities_by_org_uri_and_date_range_query(uri_or_uri_list,
                        min_date, max_date, limit=limit, include_same_as=include_same_as,
                        counts_only = counts_only)
    objs, _ = db.cypher_query(query, resolve_objects=True)
    return objs[:limit]

def build_get_activities_by_org_uri_and_date_range_query(uri_or_uri_list: Union[str,List],
                    min_date, max_date, limit=None, include_same_as=True,
                    counts_only = False):
    if isinstance(uri_or_uri_list, str):
        uri_list = [uri_or_uri_list]
    elif isinstance(uri_or_uri_list, set):
        uri_list = list(uri_or_uri_list)
    else:
        uri_list = uri_or_uri_list
    orgs = Organization.nodes.filter(uri__in=uri_list)
    uris_to_check = set(uri_list)
    if include_same_as is True:
        for org in orgs:
            new_uris = [x.uri for x in org.same_as()]
            uris_to_check.update(new_uris)
    if limit is not None:
        limit_str = f"LIMIT {limit}"
    else:
        limit_str = ""
    if counts_only is True:
        return_str = "RETURN COUNT(DISTINCT(n))"
    else:
        return_str = "RETURN n,a ORDER BY a.publishDate DESC"
    where_clause = f"""WHERE a.datePublished >= datetime('{date_to_cypher_friendly(min_date)}')
                        AND a.datePublished <= datetime('{date_to_cypher_friendly(max_date)}')
                        AND (o.uri IN {list(uris_to_check)})
                    """
    query = f"""
        MATCH (a: Article)<-[:documentSource]-(n:CorporateFinanceActivity|LocationActivity)--(o: Organization)
        {where_clause}
        {return_str} {limit_str}
        UNION
        MATCH (a: Article)<-[:documentSource]-(n:RoleActivity)--(p: Role)--(o: Organization)
        {where_clause}
        {return_str} {limit_str};
    """
    logger.debug(query)
    return query

def date_to_cypher_friendly(date):
    if isinstance(date, str):
        return datetime.fromisoformat(date).isoformat()
    else:
        return date.isoformat()

def get_cached_stats():
    latest_date = cache.get("cache_updated")
    if latest_date is None:
        return None, None, None, None
    d = datetime.date(latest_date)
    assert cache.get(f"stats_{d}") is not None
    counts, recents_by_country_region, recents_by_source =  get_stats(d, allowed_to_set_cache=False)
    return d, counts, recents_by_country_region, recents_by_source

def get_stats(max_date,allowed_to_set_cache=False):
    cache_key = f"stats_{max_date}"
    res = cache.get(cache_key)
    if res is not None:
        return res
    counts = []
    for x in ["Organization","Person","CorporateFinanceActivity","RoleActivity","LocationActivity","Article","Role"]:
        res, _ = db.cypher_query(f"MATCH (n:{x}) RETURN COUNT(n)")
        counts.append( (x , res[0][0]) )
    recents_by_country_region = []
    ts1 = datetime.utcnow()
    for k,v in geo_select_list():
        if k.strip() == '':
            continue
        cnt7 = counts_by_timedelta(7,max_date,geo_code=k)
        cnt30 = counts_by_timedelta(30,max_date,geo_code=k)
        cnt90 = counts_by_timedelta(90,max_date,geo_code=k)
        if cnt7 > 0 or cnt30 > 0 or cnt90 > 0:
            country_code = k[:2]
            recents_by_country_region.append( (country_code,k,v,cnt7,cnt30,cnt90) )
    recents_by_source = []
    for source_name in sorted(get_all_source_names()):
        cnt7 = counts_by_timedelta(7,max_date,source_name=source_name)
        cnt30 = counts_by_timedelta(30,max_date,source_name=source_name)
        cnt90 = counts_by_timedelta(90,max_date,source_name=source_name)
        if cnt7 > 0 or cnt30 > 0 or cnt90 > 0:
            recents_by_source.append( (source_name,cnt7,cnt30,cnt90) )
    ts2 = datetime.utcnow()
    logger.debug(f"counts_by_timedelta up to {max_date}: {ts2 - ts1}")
    if allowed_to_set_cache is True:
        cache.set( cache_key, (counts, recents_by_country_region, recents_by_source) )
    else:
        logger.debug("Not allowed to set cache")
    return counts, recents_by_country_region, recents_by_source

def counts_by_timedelta(days_ago, max_date, geo_code=None,source_name=None):
    min_date = max_date - timedelta(days=days_ago)
    if geo_code is not None:
        res = get_country_region_counts(geo_code,min_date,max_date)
    elif source_name is not None:
        res = get_source_counts(source_name,min_date,max_date)
    else:
        raise ValueError(f"counts_by_timedelta must supplier geo_code or source_name")
    return res

def get_source_counts(source_name, min_date,max_date):
    counts = get_activities_by_source_and_date_range(source_name,min_date,max_date,counts_only=True)
    return count_entries(counts)

def get_country_region_counts(geo_code,min_date,max_date):
    relevant_uris = get_relevant_org_uris_for_country_region_industry(geo_code,limit=None)
    counts = get_activities_by_org_uri_and_date_range(relevant_uris,min_date,max_date,include_same_as=False,counts_only=True)
    return count_entries(counts)

def count_entries(results):
    '''
        Expecting two results. For some reason, the union of two counts only returns one value if both are the same
    '''
    val = results[0][0]
    if len(results) == 1:
        val = val * 2
    else:
        val = val + results[1][0]
    return val

def get_child_orgs(uri: str, relationship = "investor|buyer|vendor")->[(Organization, ActivityMixin, Article)]:
    assert "'" not in uri, f"Can't have ' in {uri}"
    # query = f"""
    #     MATCH (a: Article)<-[:documentSource]-(c: CorporateFinanceActivity)-[:target]-(t: Organization)
    #     WHERE EXISTS {{
    #         MATCH (b: Organization)-[x:{relationship}]-(c: CorporateFinanceActivity) where b.uri = '{uri}'
    #     }}
    #     return t, c, a
    #     ORDER BY a.datePublished
    # """
    query = f"""
        MATCH (a: Article)<-[:documentSource]-(c: CorporateFinanceActivity)-[:target]-(t: Organization),
        (b: Organization)-[x:{relationship}]-(c: CorporateFinanceActivity)
        WHERE b.uri = '{uri}'
        return t, c, a, x
        ORDER BY a.datePublished
    """
    results, _ = db.cypher_query(query, resolve_objects=False)
    return results

def org_activity_articles_to_api(results):
    api_results = []
    for org_node, activity_node, article_node, parent_rel in results:
        org = Organization.inflate(org_node)
        if org is None:
            continue
        activity = CorporateFinanceActivity.inflate(activity_node)
        article = Article.inflate(article_node)
        api_row = org.serialize()
        api_row["source_organization"] = article.sourceOrganization
        api_row["date_published"] = article.datePublished
        api_row["headline"] = article.headline
        api_row["document_extract"] = activity.documentSource.relationship(article).documentExtract
        api_row["document_url"] = article.documentURL
        api_row["archive_org_page_url"] = article.archiveOrgPageURL
        api_row["archive_org_list_url"] = article.archiveOrgListURL
        api_row["activity_uri"] = activity.uri
        api_row["activity_class"] = activity.__class__.__name__
        api_row["activity_types"] = activity.activityType
        api_row["activity_longest_type"] = activity.longest_activityType
        api_row["activity_statuses"] = activity.status
        api_row["activity_status_as_string"] = activity.status_as_string
        api_row["parent_relationship_type"] = parent_rel.type
        api_results.append(api_row)
    return api_results

def get_children_for_api(orgs: List[Organization]):
    api_results = []
    for org in orgs:
        children_for_api = single_org_children(org)
        if children_for_api == []:
            continue
        api_row = {"parent_org":org.best_name,
                    "parent_org_uri":org.uri,
                    "children": children_for_api}
        api_results.append(api_row)
    return api_results

def single_org_children(org):
    children = get_child_orgs(org.uri)
    if len(children) == 0:
        return []
    children_for_api = org_activity_articles_to_api(children)
    return children_for_api
