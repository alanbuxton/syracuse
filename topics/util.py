import re
import string

def cache_friendly(key):
    no_punct = re.sub(rf"[{string.punctuation} ]","_",key)
    cleaned = re.sub(r"_{2,}","_",no_punct)
    if len(cleaned) > 230:
        cleaned = cleaned[:210] + str(hash(cleaned[210:]))
    return cleaned

def blank_or_none(val):
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == '':
        return True
    return False

def geo_to_country_admin1(geo_code):
    if geo_code is None: 
        return None, None
    splitted = geo_code.split("-")
    country_code = splitted[0]
    admin1_code = splitted[1] if len(splitted) > 1 else None
    return country_code, admin1_code

