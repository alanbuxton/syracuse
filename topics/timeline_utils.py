from topics.graph_utils import get_node_cluster
from topics.models import Organization

def get_timeline_data(orgs, limit=None):
    org_cluster_display = []
    org_cluster_nodes = []
    activities = []
    seen_orgs = set()
    errors = set()
    org_count = 0

    for org in orgs:
        if limit is not None and org_count > limit:
            break
        if org in seen_orgs:
            continue
        res = get_node_cluster(org)
        if isinstance(res, dict) and res.get("error_names") is not None:
            errors.add(org.name)
            seen_orgs.update(res["error_orgs"])
            continue
        org_count += 1
        display_data,node_cluster,_ = res
        display_data['label'] = org.longest_name
        display_data['uri'] = org.uri
        seen_orgs.update(node_cluster)
        org_cluster_display.append(display_data)
        org_cluster_nodes.append(node_cluster)
        vendor = []
        participant = []
        protagonist = []
        buyer = []
        investor = []
        role_activity = []
        location_added = []
        location_removed = []
        target = []
        for org_in_cluster in node_cluster:
            vendor.extend(org_in_cluster.vendor.all())
            participant.extend(org_in_cluster.participant.all())
#            protagonist.extend(org.protagonist.all())
            buyer.extend(org_in_cluster.buyer.all())
            investor.extend(org_in_cluster.investor.all())
            location_added.extend(org_in_cluster.locationAdded.all())
            location_removed.extend(org_in_cluster.locationRemoved.all())
            role_activity.extend(org_in_cluster.get_role_activities()) # it's a tuple
            target.extend(org_in_cluster.target.all())
        activities.append(
            {"vendor": set(vendor),
             "investor": set(investor),
             "participant": set(participant),
#             "protagonist": set(protagonist),
             "buyer": set(buyer),
             "location_added": set(location_added),
             "location_removed": set(location_removed),
             "role_activity": set(role_activity),
             "target": set(target),
             })

    groups = []
    org_display_details = {}
    activity_to_subgroup = {
        "vendor": "corporate_finance",
        "investor": "corporate_finance",
        "participant": "corporate_finance",
        "protagonist": "corporate_finance",
        "buyer": "corporate_finance",
        "location_added": "location",
        "location_removed": "location",
        "role_activity": "role",
        "target": "corporate_finance",
    }
    item_display_details = {}
    items = []
    seen_uris = set()

    for idx, x in enumerate(org_cluster_display):
        l1_group = {"id": idx, "content": x["label"], "treeLevel": 1, "nestedGroups": []}
        org_display_details[idx] = x
        for l2 in sorted(set(activity_to_subgroup.values())):
            l2_id = f"{idx}-{l2}"
            groups.append( {"id": l2_id, "content": snake_case_to_title(l2), "treeLevel": 2})
            l1_group["nestedGroups"].append(l2_id)
        groups.append(l1_group)

    for idx,activity in enumerate(activities):
        for activity_type,vs in activity.items():
            for v in vs:
                if isinstance(v, tuple):
                    current_item = v[1]
                else:
                    current_item = v
                if current_item.uri in seen_uris:
                    continue
                l2_id = f"{idx}-{activity_to_subgroup[activity_type]}"
                items.append(
                    {"group": l2_id,
                    "label": labelize(current_item,activity_type),
                    "start": current_item.documentDate,
                    "id": current_item.uri,
                    "className": class_name_for(current_item),
                    })
                item_display_details[current_item.uri] = current_item.serialize_no_none()
                seen_uris.add(current_item.uri)

    return groups, items, item_display_details, org_display_details, errors


def labelize(activity,activity_type):
    if activity.__class__.__name__ == 'RoleActivity':
        if activity.longest_activityType is None:
            label = activity.longest_name.title()
        else:
            label = activity.longest_activityType.title()
        label = f"{label} - {activity.longest_roleFoundName} - {activity.status_as_string}"
    elif activity.__class__.__name__ == 'LocationActivity':
        label = activity.longest_activityType.title()
        fields = ' '.join(filter(None, (activity.longest_name, activity.longest_locationPurpose)))
        label = f"{label} - {fields} - {activity.status_as_string}"
    else:
        label = activity.longest_activityType.title()
        fields = ' '.join(filter(None, (activity.longest_targetName,activity.longest_targetDetails)))
        label = f"{activity_type.title()} - {fields} - {activity.status_as_string} ({label})"
    return label

def class_name_for(activity):
    if activity.when is not None:
        return "activity_with_when"
    elif activity.status == "has not happened":
        return "activity_not_happened"
    else:
        return "activity_has_happened"

def snake_case_to_title(text):
    text = text.replace("_"," ")
    return text.title()
