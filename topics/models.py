from neomodel import (StructuredNode, StringProperty,
    RelationshipTo, Relationship, RelationshipFrom, db, ArrayProperty,
    IntegerProperty, StructuredRel)
from urllib.parse import urlparse
import datetime
from topics.geo_utils import get_geoname_uris_for_country_region
from syracuse.neomodel_utils import NativeDateTimeProperty
import cleanco
from django.core.cache import cache
from syracuse.settings import NEOMODEL_NEO4J_BOLT_URL
from collections import Counter
from neomodel.cardinality import OneOrMore, One
from typing import List

import logging
logger = logging.getLogger(__name__)

def uri_from_related(rel):
    if len(rel) == 0:
        return None
    return rel[0].uri

def longest(arr):
    if arr is None:
        return None
    elif isinstance(arr, str):
        return arr # Don't sort if it's just a string
    return sorted(arr,key=len)[-1]

def shortest(arr):
    if arr is None:
        return None
    elif isinstance(arr, str):
        return arr # Don't sort if it's just a string
    return sorted(arr,key=len)[0]

class DocumentSourceRel(StructuredRel):
    documentExtract = StringProperty()

class Resource(StructuredNode):
    uri = StringProperty(unique_index=True, required=True)
    foundName = ArrayProperty(StringProperty())
    name = ArrayProperty(StringProperty())
    documentSource = RelationshipTo("Article","documentSource",
            model=DocumentSourceRel, cardinality=OneOrMore) # But not for Article or IndustryCluster
    internalDocId = IntegerProperty()
    sameAsNameOnly = Relationship('Resource','sameAsNameOnly')
    sameAsHigh = Relationship('Resource','sameAsHigh')
    internalMergedSameAsHighToUri = StringProperty()

    @property
    def related_articles(self):
        cache_key = f"{self.uri}_related_articles"
        arts = cache.get(cache_key)
        if arts is not None:
            return arts
        if isinstance(self, Article) is True or isinstance(self, IndustryCluster) is True:
            arts = None
        else:
            arts = self.documentSource.all()
        cache.set(cache_key,arts)
        return arts
    
    def has_permitted_document_source(self,source_names):
        if isinstance(self, IndustryCluster):
            # Industry Clusters are always legitimate to show because they didn't come from specific articles
            return True 
        if hasattr(self, "sourceOrganization") and self.sourceOrganization in source_names:
            return True
        for x in self.related_articles or []:
            if x.sourceOrganization in source_names:
                return True
        return False

    @staticmethod
    def get_by_uri(uri):
        return Resource.nodes.get(uri)

    @classmethod
    def unmerged_or_none_by_uri(cls, uri):
        return cls.unmerged_or_none({"uri":uri})

    @classmethod
    def unmerged_or_none(cls,params):
        return cls.nodes.filter(internalMergedSameAsHighToUri__isnull=True).get_or_none(**params)

    @classmethod
    def randomized_active_nodes(cls,limit=10):
        query = f"""MATCH (n: Resource:{cls.__name__})
                    WHERE n.internalMergedSameAsHighToUri IS NULL
                    AND NOT (n)-[:sameAsNameOnly]-()
                    RETURN n,rand() as r
                    ORDER BY r
                    LIMIT {limit}"""
        res,_ = db.cypher_query(query, resolve_objects=True)
        return [x[0] for x in res]

    @property
    def industry_as_str(self):
        pass # override in relevant subclass

    @property
    def basedInHighGeoName_as_str(self):
        pass # override in relevant subclass - if in Mixin make sure Mixin is first https://stackoverflow.com/a/34090986/7414500

    @property
    def whereGeoName_as_str(self):
        pass # override in relevant subclass - if in Mixin make sure Mixin is first https://stackoverflow.com/a/34090986/7414500

    @property
    def earliestDocumentSource(self):
        return self.documentSource.order_by("datePublished")[0]

    @property
    def earliestDatePublished(self):
        return self.earliestDocumentSource.datePublished

    @staticmethod
    def self_or_ultimate_target_node(uri_or_object):
        if isinstance(uri_or_object, str):
            r = Resource.nodes.get_or_none(uri=uri_or_object)
        else:
            r = uri_or_object
        if r is None:
            return None
        elif r.internalMergedSameAsHighToUri is None:
            return r
        else:
            return Resource.self_or_ultimate_target_node(r.internalMergedSameAsHighToUri)

    @staticmethod
    def self_or_ultimate_target_node_set(uris_or_objects: List):
        items = [Resource.self_or_ultimate_target_node(x) for x  in uris_or_objects]
        return list(set(items))

    @property
    def sourceDocumentURL(self):
        return uri_from_related(self.documentURL)

    @property
    def sourceName(self):
        docs = self.documentSource
        if docs is None or len(docs) == 0:
            return ''
        return self.documentSource[0].sourceOrganization

    def ensure_connection(self):
        if self.element_id_property is not None and db.database_version is None:
            # Sometimes seeing "_new_traversal() attempted on unsaved node" even though node is saved
            db.set_connection(NEOMODEL_NEO4J_BOLT_URL)

    @classmethod
    def find_by_name(cls, name, combine_same_as_name_only):
        name = name.lower()
        cache_key = f"{cls.__name__}_{name}_{combine_same_as_name_only}"
        res = cache.get(cache_key)
        if res is not None:
            logger.debug(f"From cache {cache_key}")
            return res
        objs1 = cls.find_by_name_optional_same_as_onlies(name,combine_same_as_name_only)
        if combine_same_as_name_only is True:
            objs2 = cls.get_first_same_as_name_onlies(name)
        else:
            objs2 = []
        objs = set(objs1 + objs2)
        cache.set(cache_key, objs)
        return objs

    @classmethod
    def find_by_name_optional_same_as_onlies(cls, name, exclude_same_as_onlies):
        query = f'''MATCH (n: {cls.__name__})
                    WHERE ANY (item IN n.name WHERE item =~ "(?i).*{name}.*")
                    AND n.internalMergedSameAsHighToUri IS NULL '''
        if exclude_same_as_onlies is True:
            query = f"{query} AND NOT (n)-[:sameAsNameOnly]-() "
        query = query + " RETURN n"
        results, _ = db.cypher_query(query,resolve_objects=True)
        objs = [x[0] for x in results]
        return objs

    @classmethod
    def get_first_same_as_name_onlies(cls, name):
        query = f"""MATCH (n: {cls.__name__})-[:sameAsNameOnly]-(o)
                    WHERE ANY (item IN n.name WHERE item =~ "(?i).*{name}.*")
                    AND n.internalMergedSameAsHighToUri IS NULL
                    AND o.internalMergedSameAsHighToUri IS NULL
                    AND n.internalDocId <= o.internalDocId
                    RETURN n,o ORDER BY n.internalDocId"""
        results,_ = db.cypher_query(query, resolve_objects=True)
        entities_to_keep = []
        found_uris = set()
        for source, target in results:
            found_uris.add(target.uri)
            if source.uri in found_uris:
                continue
            entities_to_keep.append(source)     
            found_uris.add(source.uri)
        return entities_to_keep

    @property
    def best_name(self):
        # Should override in child classes if better way to come up with display name
        return self.longest_name

    @property
    def longest_name(self):
        return longest(self.name)

    @property
    def shortest_name(self):
        return shortest(self.name)

    def __hash__(self):
        return hash(self.uri)

    def __eq__(self,other):
        return self.uri == other.uri

    def serialize(self):
        self.ensure_connection()
        return {
            "entity_type": self.__class__.__name__,
            "label": self.best_name,
            "name": self.name,
            "uri": self.uri,
        }

    def serialize_no_none(self):
        vals = self.serialize()
        return {k:v for k,v in vals.items() if v is not None}

    def split_uri(self):
        parsed_uri = urlparse(self.uri)
        splitted_uri = parsed_uri.path.split("/") # first element is empty string because path starts with /
        assert len(splitted_uri) == 4, f"Expected {self.uri} path to have exactly 3 parts but it has {len(splitted_uri)}"
        return {
            "domain": parsed_uri.netloc,
            "path": splitted_uri[1],
            "doc_id": splitted_uri[2],
            "name": splitted_uri[3],
        }

    def all_directional_relationships(self, **kwargs):
        '''
            Returns dicts:
            from_uri
            label: relationship label
            direction:
            other_node:
            relationship_data: (only if source is Activity and other node is Article)
        '''
        override_from_uri = kwargs.get("override_from_uri")
        source_names = kwargs.get("source_names")
        if override_from_uri is not None:
            from_uri = override_from_uri
        else:
            from_uri = self.uri
        all_rels = []
        logger.debug(f"Source node: {self.uri} - has permitted source with {source_names}? {self.has_permitted_document_source(source_names)}")
        for key, rel in self.__all_relationships__:
            if isinstance(rel, RelationshipTo):
                direction = "to"
            elif isinstance(rel, RelationshipFrom):
                direction = "from"
            else:
                continue

            for x in self.__dict__[key]:
                other_node = Resource.self_or_ultimate_target_node(x)
                if other_node.has_permitted_document_source(source_names) is False:
                    logger.debug(f"Skipping {other_node.uri} due to invalid source_names")
                    continue
                logger.debug(f"Working on {other_node.uri}")
                vals = {"from_uri": from_uri, "label":key, "direction":direction, "other_node":other_node}
                if isinstance(self, ActivityMixin) and isinstance(x, Article):
                    document_extract = self.documentSource.relationship(x).documentExtract
                    vals["document_extract"] = document_extract
                elif isinstance(self, Article) and isinstance(x, ActivityMixin):
                    document_extract = self.relatedEntity.relationship(x).documentExtract
                    vals["document_extract"] = document_extract
                if vals not in all_rels:
                    all_rels.append( vals )
        return all_rels

    @staticmethod
    def merge_node_connections(source_node, target_node):
        for rel_key,_ in source_node.__all_relationships__:
            if rel_key.startswith("sameAs"):
                logger.debug(f"ignoring {rel_key}")
                continue
            for other_node in source_node.__dict__[rel_key].all():
                logger.debug(f"connecting {other_node.uri} to {target_node.uri}")
                new_rel = target_node.__dict__[rel_key].connect(other_node)
                old_rel = source_node.__dict__[rel_key].relationship(other_node)
                if hasattr(old_rel, 'documentExtract'):
                    new_rel.documentExtract = old_rel.documentExtract
                    new_rel.save()
            source_node.internalMergedSameAsHighToUri = target_node.uri
            source_node.save()
            target_node.save()


class Article(Resource):
    headline = StringProperty(required=True)
    url = Relationship("Resource","url", cardinality=One)
    sourceOrganization = StringProperty(required=True)
    datePublished = NativeDateTimeProperty(required=True)
    dateRetrieved = NativeDateTimeProperty(required=True)
    relatedEntity = RelationshipFrom("Resource","documentSource",
            model=DocumentSourceRel, cardinality=OneOrMore)
    
    @staticmethod
    def available_source_names_dict():
        cache_key = "available_source_names"
        sources = cache.get(cache_key)
        if sources is not None:
            return sources
        res = db.cypher_query("MATCH (n: Resource:Article) RETURN DISTINCT(n.sourceOrganization)")
        sources = {x[0].lower():x[0] for x in res[0]}
        assert None not in sources, f"We have an Article with None sourceOrganization"
        cache.set(cache_key,sources)
        return sources
    
    @staticmethod
    def all_sources():
        return list(Article.available_source_names_dict().values())
    
    @staticmethod
    def core_sources():
        '''
            Generic, high quality sources that we get good results with.
            Will run with newer data sources for a while before adding them to this list.
        '''
        return [
            'Associated Press',
            'Business Insider',
            'Business Wire',
            'CNN',
            'CNN International',
            'GlobeNewswire',
            'Indiatimes',
            'PR Newswire',
            'Sifted',
            'South China Morning Post',
            'TechCrunch',
            'The Globe and Mail',
            'prweb',
        ]

    @property
    def archive_date(self):
        closest_date = self.dateRetrieved or self.datePublished
        return closest_date.strftime("%Y%m%d")

    @property
    def archiveOrgPageURL(self):
        return f"https://web.archive.org/{self.archive_date}235959/{self.documentURL}"

    @property
    def archiveOrgListURL(self):
        return f"https://web.archive.org/{self.archive_date}*/{self.documentURL}"

    @property
    def best_name(self):
        return self.headline

    @property
    def documentURL(self):
        return self.url[0].uri

    def serialize(self):
        vals = super(Article, self).serialize()
        vals['headline'] = self.best_name
        vals['document_url'] = self.documentURL
        vals['source_organization'] = self.sourceOrganization
        vals['date_published'] = self.datePublished
        vals['date_retrieved'] = self.dateRetrieved
        vals['internet_archive_page_url'] = self.archiveOrgPageURL
        vals['internet_archive_list_url'] = self.archiveOrgListURL
        return vals


class IndustryCluster(Resource):
    representation = ArrayProperty(StringProperty())
    representativeDoc = ArrayProperty(StringProperty())
    childRight = RelationshipTo("IndustryCluster","childRight")
    childLeft = RelationshipTo("IndustryCluster","childLeft")
    parentsLeft = RelationshipFrom("IndustryCluster","childLeft")
    parentsRight = RelationshipFrom("IndustryCluster","childRight")
    topicId = IntegerProperty()
    uniqueName = StringProperty()
    orgsPrimary = RelationshipFrom("Organization","industryClusterPrimary")
    orgsSecondary = RelationshipFrom("Organization","industryClusterSecondary")
    peoplePrimary = RelationshipFrom("Person","industryClusterPrimary")
    peopleSecondary = RelationshipFrom("Person","industryClusterSecondary")

    def serialize(self):
        vals = super(IndustryCluster, self).serialize()
        if self.representativeDoc is None:
            name_words = self.uniqueName.split("_")[1:]
            name_words = ", ".join(name_words)
        else:
            name_words = sorted(self.representativeDoc, key=len)[-1]
        vals['label'] = name_words
        vals['representative_doc'] = (", ").join(self.representativeDoc) if self.representativeDoc else None
        vals['internal_cluster_id'] = self.topicId
        vals['unique_name'] = self.uniqueName
        vals['representation'] = (", ").join(self.representation) if self.representation else None
        return vals

    @staticmethod
    def representative_docs_to_industry():
        docs_to_industry_uri = []
        for ind in IndustryCluster.nodes.filter(representativeDoc__isnull=False):
            if ind.topicId == -1:
                continue
            longest_doc = sorted(ind.representativeDoc,key=len)[-1]
            docs_to_industry_uri.append( (ind.topicId, longest_doc))
        return docs_to_industry_uri

    @property
    def parents(self):
        return self.parentsLeft.all() + self.parentsRight.all()

    @staticmethod
    def leaf_keywords(ignore_cache=False):
        cache_key = "industry_leaf_keywords"
        res = cache.get(cache_key)
        if res is not None and ignore_cache is False:
            return res
        keywords = {}
        for node in IndustryCluster.leaf_nodes_only():
            words = node.uniqueName.split("_")
            idx = words[0]
            for word in words[1:]:
                if word not in keywords.keys():
                    keywords[word] = set()
                keywords[word].add(idx)
        cache.set(cache_key, keywords)
        return keywords

    @staticmethod
    def top_node():
        query = "MATCH (n: IndustryCluster) WHERE NOT (n)<-[:childLeft|childRight]-(:IndustryCluster) AND n.topicId <> -1 return n"
        results, _ = db.cypher_query(query,resolve_objects=True)
        return results[0][0]

    @staticmethod
    def leaf_nodes_only():
        query = "MATCH (n: IndustryCluster) WHERE NOT (n)-[:childLeft|childRight]->(:IndustryCluster) RETURN n"
        results, _ = db.cypher_query(query,resolve_objects=True)
        flattened = [x for sublist in results for x in sublist]
        return flattened

    @staticmethod
    def parents_of(nodes):
        parent_objects = []
        for node in nodes:
            for p in node.parents:
                if p not in nodes:
                    parent_objects.append(p)
        return parent_objects

    @staticmethod
    def first_parents():
        return IndustryCluster.parents_of(IndustryCluster.leaf_nodes_only())

    @staticmethod
    def second_parents():
        return IndustryCluster.parents_of(IndustryCluster.first_parents())

    @staticmethod
    def with_descendants(topic_id,max_depth=500):
        if topic_id is None:
            return None
        root = IndustryCluster.nodes.get_or_none(topicId=topic_id)
        if root is None:
            return []
        descendant_uris,_ = db.cypher_query(f"MATCH (n: IndustryCluster {{uri:'{root.uri}'}})-[x:childLeft|childRight*..{max_depth}]->(o: IndustryCluster) return o.uri;")
        flattened = [x for sublist in descendant_uris for x in sublist]
        return [root.uri] + flattened

    @property
    def friendly_name_and_id(self):
        vals = self.uniqueName.split("_")
        name = ", ".join(vals[1:]).title()
        return name, vals[0]


class ActivityMixin:
    activityType = ArrayProperty(StringProperty())
    when = ArrayProperty(NativeDateTimeProperty())
    whenRaw = ArrayProperty(StringProperty())
    status = ArrayProperty(StringProperty())
    whereRaw = ArrayProperty(StringProperty())
    whereClean = ArrayProperty(StringProperty())
    whereGeoNamesLocation = RelationshipTo('GeoNamesLocation','whereGeoNamesLocation')

    @property
    def whereGeoName_as_str(self):
        cache_key = f"{self.__class__.__name__}_activity_mixin_name_{self.uri}"
        names = cache.get(cache_key)
        if names is not None:
            return names
        names = []
        for x in self.whereGeoNamesLocation:
            if x.name is None:
                continue
            names.extend(x.name)
        name = print_friendly(names)
        cache.set(cache_key,name)
        return name

    @property
    def longest_activityType(self):
        return longest(self.activityType)

    @property
    def status_as_string(self):
        if len(self.status) > 1:
            return "unknown"
        elif self.status[0] == "has not happened":
            return "unknown"
        else:
            return self.status[0]

    @property
    def activity_fields(self):
        if self.activityType is None:
            activityType_title = "Activity"
        else:
            activityType_title = self.longest_activityType.title()
        return {
            "activity_type": activityType_title,
            "label": f"{activityType_title} ({self.sourceName}: {self.earliestDatePublished.strftime('%b %Y')})",
            "status": self.status,
            "when": self.when,
            "when_raw": self.whenRaw,
            "where_raw": self.whereRaw,
            "where_clean": self.whereClean,
        }

    @property
    def whereGeoNameRDFURL(self):
        return [x.uri for x in self.whereGeoNameRDF]

    @property
    def whereGeoNameURL(self):
        uris = []
        for x in self.whereGeoNameRDF:
            uri = x.uri.replace("/about.rdf","")
            uris.append(uri)
        return uris

class GeoNamesLocation(Resource):
    geoNamesId = IntegerProperty()
    geoNames = Relationship('Resource','geoNames')

    @property
    def geoNamesURL(self):
        return uri_from_related(self.geoNames)

    @property
    def geoNamesRDFURL(self):
        if self.geoNamesURL is None:
            return None
        uri = self.geoNamesURL + "/about.rdf"
        return uri

    def serialize(self):
        vals = super(GeoNamesLocation, self).serialize()
        vals['geonames_id'] = self.geoNamesId
        vals['geonames_rdf_url'] = self.geoNamesRDFURL
        vals['geonames_url'] = self.geoNamesURL
        return vals

    @staticmethod
    def uris_by_geo_code(geo_code):
        if geo_code is None or geo_code.strip() == '':
            return None
        cache_key = f"geonames_locations_{geo_code}"
        res = cache.get(cache_key)
        if res is not None:
            return res
        geonames_uris = get_geoname_uris_for_country_region(geo_code)
        vals, _ = db.cypher_query(f"""MATCH (n: GeoNamesLocation)-[:geoNamesURL]-(r: Resource)
                                    WHERE r.uri in {geonames_uris} RETURN n""",resolve_objects=True)
        uris = [x[0].uri for x in vals]
        cache.set(cache_key, uris)
        return uris


class Organization(Resource):
    description = ArrayProperty(StringProperty())
    industry = ArrayProperty(StringProperty())
    investor = RelationshipTo('CorporateFinanceActivity','investor')
    buyer =  RelationshipTo('CorporateFinanceActivity', 'buyer')
    protagonist = RelationshipTo('CorporateFinanceActivity', 'protagonist')
    participant = RelationshipTo('CorporateFinanceActivity', 'participant')
    vendor = RelationshipFrom('CorporateFinanceActivity', 'vendor')
    target = RelationshipFrom('CorporateFinanceActivity', 'target')
    hasRole = RelationshipTo('Role','hasRole')
    locationAdded = RelationshipTo('LocationActivity','locationAdded')
    locationRemoved = RelationshipTo('LocationActivity','locationRemoved')
    industryClusterPrimary = RelationshipTo('IndustryCluster','industryClusterPrimary')
    # industryClusterSecondary = RelationshipTo('IndustryCluster','industryClusterSecondary')
    basedInHighGeoNamesLocation = RelationshipTo('GeoNamesLocation','basedInHighGeoNamesLocation')
    basedInHighRaw = ArrayProperty(StringProperty())
    basedInHighClean = ArrayProperty(StringProperty())

    @property
    def industry_as_str(self):
        by_popularity = self.get_industry_list()
        if len(by_popularity) == 0:
            return None
        return print_friendly(by_popularity)

    def get_industry_list(self):
        cache_key = f"industries_{self.uri}"
        name = cache.get(cache_key)
        if name is not None:
            return name
        name_cands = (self.industry or []) + [] # ensure this is a copy of self.industry
        for x in self.sameAsHigh:
            if x.industry is not None:
                name_cands.extend(x.industry)
        name_counter = Counter(sorted(name_cands,key=len))
        by_popularity = [x[0].title() for x in name_counter.most_common()]
        cache.set(cache_key,by_popularity)
        return by_popularity

    def reset_cache(self):
        cache_key = f"org_name_{self.uri}"
        cache.delete(cache_key)
        cache_key = f"industries_{self.uri}"
        cache.delete(cache_key)

    @property
    def best_name(self):
        cache_key = f"org_name_{self.uri}"
        name = cache.get(cache_key)
        if name is not None:
            return name
        name_cands = (self.name or []) + [] # Ensure name_cands is a copy
        for x in self.sameAsHigh:
            if x.name is not None:
                name_cands.extend(x.name)
        name_counter = Counter(name_cands)
        top_name = name_counter.most_common(1)[0][0]
        cache.set(cache_key, top_name)
        return top_name

    @staticmethod
    def get_best_name_by_uri(uri):
        org = Organization.self_or_ultimate_target_node(uri)
        if org is not None:
            return org.best_name

    @staticmethod
    def by_uris(uris):
        return Organization.nodes.filter(uri__in=uris)

    @staticmethod
    def get_random():
        return Organization.nodes.order_by('?')[0]

    @property
    def shortest_name_length(self):
        words = shortest(self.name)
        if words is None:
            return 0
        return len(cleanco.basename(words).split())

    def serialize(self):
        vals = super(Organization, self).serialize()
        org_vals = {"description": self.description,
                    "industry": self.industry_as_str,
                    "based_in_high_raw": self.basedInHighRaw,
                    "based_in_high_clean": self.basedInHighClean,
                    }
        return {**vals,**org_vals}

    def get_role_activities(self,source_names=Article.core_sources()):
        role_activities = []
        for role in self.hasRole:
            acts = role.withRole.all()
            role_activities.extend([(role,act) for act in acts if act.has_permitted_document_source(source_names)])
        return role_activities

    @staticmethod
    def by_industry_and_or_geo(industry_id, geo_code,uris_only=False,limit=None,allowed_to_set_cache=False):
        cache_key = f"organization_by_industry_and_or_geo_{industry_id}_{geo_code}_{uris_only}_{limit}"
        vals = cache.get(cache_key)
        if vals is not None:
            return vals
        logger.debug(f"Checking Geo Code: {geo_code} Industry ID: {industry_id}")
        industry_uris = IndustryCluster.with_descendants(industry_id)
        geo_uris = GeoNamesLocation.uris_by_geo_code(geo_code)
        if industry_uris is None and geo_uris is None:
            return None
        match1 = None
        match2 = None
        where1 = None
        where2 = None
        if industry_uris is not None:
            match1 = "(n: Organization)-[:industryClusterPrimary]-(i: IndustryCluster) "
            where1 = f" i.uri IN {industry_uris} "
        if geo_uris is not None:
            match2 = "(n: Organization)-[:basedInHighGeoNamesLocation]-(g: GeoNamesLocation) "
            where2 = f" g.uri IN {geo_uris} "
        if industry_uris is None and geo_uris is not None:
            query = f"MATCH {match2} WHERE {where2} AND n.internalMergedSameAsHighToUri IS NULL RETURN DISTINCT(n) "
        elif industry_uris is not None and geo_uris is None:
            query = f"MATCH {match1} WHERE {where1} AND n.internalMergedSameAsHighToUri IS NULL RETURN DISTINCT(n) "
        else:
            query = f"MATCH {match1}, {match2} WHERE {where1} AND {where2} AND n.internalMergedSameAsHighToUri IS NULL RETURN DISTINCT(n) "
        if limit is not None:
            query = f"{query} LIMIT {limit}"
        logger.debug(query)
        vals, _ = db.cypher_query(query, resolve_objects=True)
        if uris_only is True:
            res = [x[0].uri for x in vals]
            if allowed_to_set_cache is True:
                cache.set(cache_key,res)
            return res
        else:
            res = [x[0] for x in vals]
            if allowed_to_set_cache is True:
                cache.set(cache_key,res)
            return res

class CorporateFinanceActivity(ActivityMixin, Resource):
    targetDetails = ArrayProperty(StringProperty())
    valueRaw = ArrayProperty(StringProperty())
    target = RelationshipTo('Organization','target')
    targetName = ArrayProperty(StringProperty())
    vendor = RelationshipTo('Organization','vendor')
    investor = RelationshipFrom('Organization','investor')
    buyer =  RelationshipFrom('Organization', 'buyer')
    protagonist = RelationshipFrom('Organization', 'protagonist')
    participant = RelationshipFrom('Organization', 'participant')

    @property
    def all_actors(self):
        return {
            "vendor": Resource.self_or_ultimate_target_node_set(self.vendor),
            "investor": Resource.self_or_ultimate_target_node_set(self.investor),
            "buyer": Resource.self_or_ultimate_target_node_set(self.buyer),
            "protagonist": Resource.self_or_ultimate_target_node_set(self.protagonist),
            "participant": Resource.self_or_ultimate_target_node_set(self.participant),
            "target": Resource.self_or_ultimate_target_node_set(self.target),
        }

    @property
    def longest_targetName(self):
        return longest(self.targetName)

    @property
    def longest_targetDetails(self):
        return longest(self.targetDetails)

    def serialize(self):
        vals = super(CorporateFinanceActivity, self).serialize()
        activity_mixin_vals = self.activity_fields
        act_vals = {
                    "target_details": self.targetDetails,
                    "value_raw": self.valueRaw,
                    "target_name": self.targetName,
                    }
        return {**vals,**act_vals,**activity_mixin_vals}


class RoleActivity(ActivityMixin, Resource):
    orgFoundName = ArrayProperty(StringProperty())
    withRole = RelationshipTo('Role','role')
    roleFoundName = ArrayProperty(StringProperty())
    roleHolderFoundName = ArrayProperty(StringProperty())
    roleActivity = RelationshipFrom('Person','roleActivity')

    def related_orgs(self):
        query = f"MATCH (n: RoleActivity {{uri:'{self.uri}'}})--(o: Role)--(p: Organization) RETURN p"
        objs, _ = db.cypher_query(query,resolve_objects=True)
        flattened = [x for sublist in objs for x in sublist]
        return flattened

    @property
    def all_actors(self):
        return {
        "role": self.withRole.all(),
        "person": self.roleActivity.all(),
        "organization": self.related_orgs(),
        }

    @property
    def longest_roleFoundName(self):
        return longest(self.roleFoundName)

    def serialize(self):
        vals = super(RoleActivity, self).serialize()
        activity_mixin_vals = self.activity_fields
        act_vals = {
                    "org_found_name": self.orgFoundName,
                    "role_found_name": self.roleFoundName,
                    "role_holder_found_name": self.roleHolderFoundName,
                    }
        return {**vals,**act_vals,**activity_mixin_vals}

class LocationActivity(ActivityMixin, Resource):
    actionFoundName = ArrayProperty(StringProperty())
    locationFoundName = ArrayProperty(StringProperty())
    locationPurpose = ArrayProperty(StringProperty())
    locationType = ArrayProperty(StringProperty())
    orgFoundName = ArrayProperty(StringProperty())
    locationAdded = RelationshipFrom('Organization','locationAdded')
    locationRemoved = RelationshipFrom('Organization','locationRemoved')
    location = RelationshipTo('Site', 'location')

    @property
    def all_actors(self):
        return {
            "location_added_by": self.locationAdded.all(),
            "location_removed_by": self.locationRemoved.all(),
            "location": self.location.all(),
        }

    @property
    def longest_locationPurpose(self):
        return longest(self.locationPurpose)

    def serialize(self):
        vals = super(LocationActivity, self).serialize()
        activity_fields = self.activity_fields
        act_vals = {
                    "action_found_name": self.actionFoundName,
                    "location_purpose": self.locationPurpose,
                    "location_type": self.locationType,
                    }
        return {**vals,**act_vals,**activity_fields}

class Site(Resource):
    nameClean = StringProperty()
    location = RelationshipFrom('LocationActivity','location')
    nameGeoNamesLocation = RelationshipTo('GeoNamesLocation','nameGeoNamesLocation')
    basedInHighGeoNamesLocation = RelationshipTo('GeoNamesLocation','basedInHighGeoNamesLocation')

    @property
    def nameGeoNamesLocationRDFURL(self):
        return uri_from_related(self.nameGeoNamesLocation)

    @property
    def nameGeoNamesLocationURL(self):
        uri = uri_from_related(self.nameGeoNamesLocation)
        if uri:
            uri = uri.replace("/about.rdf","")
        return uri

    @property
    def basedInHighGeoNamesLocationRDFURL(self):
        return uri_from_related(self.basedInHighGeoNamesLocation)

    @property
    def basedInHighGeoNamesLocationURL(self):
        uri = uri_from_related(self.basedInHighGeoNamesLocation)
        if uri:
            uri = uri.replace("/about.rdf","")
        return uri


class Person(Resource):
    roleActivity = RelationshipTo('RoleActivity','roleActivity')
    industryClusterPrimary = RelationshipTo('IndustryCluster','industryClusterPrimary')
    industryClusterSecondary = RelationshipTo('IndustryCluster','industryClusterSecondary')


class Role(Resource):
    orgFoundName = ArrayProperty(StringProperty())
    withRole = RelationshipFrom("RoleActivity","role") # prefix needed or doesn't pick up related items
    hasRole = RelationshipFrom('Organization','hasRole')

class OrganizationSite(Organization, Site):
    __class_name_is_label__ = False

class CorporateFinanceActivityOrganization(Organization, CorporateFinanceActivity):
    __class_name_is_label__ = False

class OrganizationPerson(Organization, Person):
    __class_name_is_label__ = False

class OrganizationRolePerson(Organization, Role, Person):
    __class_name_is_label__ = False

class OrganizationRole(Organization, Role):
    __class_name_is_label__ = False


def print_friendly(vals, limit = 2):
    if vals is None:
        return None
    first_n = vals[:limit]
    val = ", ".join(first_n)
    extras = len(vals[limit:])
    if extras > 0:
        val = f"{val} and {extras} more"
    return val


def date_for_cypher(a_date):
    return f"datetime({{ year: {a_date.year}, month: {a_date.month}, day: {a_date.day} }})"
