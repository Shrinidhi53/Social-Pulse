"""Identify concrete Tata STRIVE training and course enquiries from social content."""
import re

from app.brand_filter import mentions_tata_strive

COURSE_URL = "https://tatastrive.com/what-we-do/courses/"

COURSES = (
    {"title": "AWS re/start", "category": "Cloud computing", "keywords": ("aws", "cloud computing", "cloud skills")},
    {"title": "Full Stack Java Developer", "category": "Software development", "keywords": ("java", "full stack", "programming", "coding", "software developer")},
    {"title": "Cybershikshaa +", "category": "Cybersecurity", "keywords": ("cybershikshaa", "cyber security", "cybersecurity", "information security")},
    {"title": "Google UX Design Professional", "category": "UX and digital design", "keywords": ("ux design", "user experience", "ui design")},
    {"title": "Electric Vehicle Service Technician", "category": "Electric vehicle servicing", "keywords": ("electric vehicle", "ev technician", "ev servicing")},
    {"title": "Commis Chef", "category": "Hospitality and food service", "keywords": ("chef", "cooking", "culinary", "food service")},
    {"title": "Front Office Associate", "category": "Hospitality", "keywords": ("hotel reception", "front office", "hospitality")},
    {"title": "Retail Sales Associate", "category": "Retail and sales", "keywords": ("retail", "sales associate", "retail sales")},
    {"title": "Assistant Electrician", "category": "Electrical work", "keywords": ("electrician", "electrical wiring", "electrical technician")},
    {"title": "Solar PV Installer (Suryamitra)", "category": "Solar energy", "keywords": ("solar", "solar energy", "solar panel")},
    {"title": "Entrepreneurship Development Program", "category": "Entrepreneurship", "keywords": ("entrepreneurship", "start a business", "small business")},
    {"title": "Guided Short Courses – Communication Skills", "category": "Communication skills", "keywords": ("communication skills", "spoken english", "soft skills")},
)

CAPABILITY_CATALOGUE = (
    {"capability": "Electric mobility and automotive technician skills", "keywords": ("electric vehicle", "ev technician", "automotive", "vehicle servicing", "auto technician")},
    {"capability": "Renewable energy and solar installation skills", "keywords": ("solar", "renewable energy", "solar pv", "green jobs", "clean energy")},
    {"capability": "Digital, cloud, and software skills", "keywords": ("cloud", "aws", "software", "full stack", "coding", "digital skills", "technology")},
    {"capability": "Cybersecurity skills", "keywords": ("cyber security", "cybersecurity", "information security", "security analyst")},
    {"capability": "Hospitality and food service skills", "keywords": ("hospitality", "hotel", "tourism", "chef", "food service")},
    {"capability": "Retail and customer service skills", "keywords": ("retail", "sales associate", "customer service", "front office")},
    {"capability": "Entrepreneurship and small business skills", "keywords": ("entrepreneur", "entrepreneurship", "small business", "self employment")},
    {"capability": "Work readiness and communication skills", "keywords": ("interview", "job readiness", "communication skills", "employability", "work readiness")},
)


def match_capabilities(text: str, limit: int = 3) -> list[dict]:
    """Return transparent candidate matches; catalogue matches are hypotheses, not verified fit."""
    normalized = re.sub(r"\s+", " ", text.casefold())
    matches = []
    for entry in CAPABILITY_CATALOGUE:
        evidence = [term for term in entry["keywords"] if _contains_keyword(normalized, term)]
        if evidence:
            score = min(0.95, 0.5 + 0.15 * len(evidence) + (0.1 if len(evidence[0]) >= 8 else 0))
            matches.append({"capability": entry["capability"], "score": round(score, 2),
                            "matched_terms": evidence, "review_required": True,
                            "match_note": "Keyword overlap only; confirm current Tata STRIVE capability, delivery location, and partner need."})
    return sorted(matches, key=lambda item: (-item["score"], item["capability"]))[:limit]

_ASK_CUES = (
    "where can i", "where do i", "where to", "from where", "how can i", "how do i", "how to",
    "which course", "what course", "what skills", "what should i", "what can i do", "what to do",
    "looking for", "want to learn", "need training", "need a course", "interested in", "can you suggest",
    "please suggest", "please guide", "any course", "any training", "tell me about", "enroll", "enrol",
    "admission", "apply for", "join a course", "join the course", "course near", "training near",
    "looking to upskill", "want to upskill", "need to upskill", "how to upskill", "seeking training",
    "seeking to learn", "interested to learn", "keen to learn",
)
_TRAINING_TERMS = ("training", "course", "courses", "skill", "skills", "learn", "learning", "certification", "certified", "upskill", "vocational")
_LOCATION_CUES = ("where", "location", "centre", "center", "near me", "nearby", "from where", "in which city")
_INDIAN_PLACES = (
    "New Delhi", "Delhi", "Mumbai", "Bengaluru", "Bangalore", "Chennai", "Hyderabad", "Kolkata", "Pune",
    "Ahmedabad", "Jaipur", "Lucknow", "Patna", "Bhopal", "Indore", "Surat", "Vadodara", "Nagpur", "Kochi",
    "Thiruvananthapuram", "Bhubaneswar", "Chandigarh", "Noida", "Gurugram", "Gurgaon", "Ghaziabad", "Varanasi",
    "Ranchi", "Dehradun", "Mysuru", "Mysore", "Mangaluru", "Mangalore", "Coimbatore", "Visakhapatnam", "Guwahati",
    "Jamshedpur", "Nashik", "Amritsar", "India",
)


def _extract_location(text: str) -> str | None:
    if re.search(r"\bnear me\b|\bnearby\b", text, re.IGNORECASE):
        return "near me"
    for place in sorted(_INDIAN_PLACES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(place)}\b", text, re.IGNORECASE):
            return place
    return None


def _contains_keyword(text: str, keyword: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(keyword.casefold())}(?!\w)", text))


def classify_training_opportunity(text: str, require_brand: bool = True) -> dict | None:
    """Find a concrete training request; direct Tata STRIVE matching remains the reply safety gate."""
    if not text or (require_brand and not mentions_tata_strive(text)):
        return None
    normalized = re.sub(r"\s+", " ", text.casefold())
    # Ignore promotional copy and unrelated job-scam checks that quote a brand.
    if any(phrase in normalized for phrase in ("courses offered by", "we provide", "join the training immediately", "alternative institute", "whatsapp msg", "whatsapp message")):
        return None
    has_training_topic = any(term in normalized for term in _TRAINING_TERMS)
    asks_for_help = any(cue in normalized for cue in _ASK_CUES) or ("?" in text and has_training_topic)
    if not has_training_topic or not asks_for_help:
        return None

    location = _extract_location(text)
    asks_location = any(cue in normalized for cue in _LOCATION_CUES)
    if asks_location:
        request_type = "course_location" if any(term in normalized for term in ("course", "training", "centre", "center", "location")) else "location_guidance"
    elif any(term in normalized for term in ("course", "training", "certification", "admission", "enroll", "enrol")):
        request_type = "course_information"
    else:
        request_type = "skill_guidance"

    matched_skills: list[str] = []
    for course in COURSES:
        for keyword in course["keywords"]:
            if _contains_keyword(normalized, keyword) and course["category"] not in matched_skills:
                matched_skills.append(course["category"])
                break

    matching_courses = []
    for course in COURSES:
        score = sum(_contains_keyword(normalized, keyword) for keyword in course["keywords"])
        if score:
            matching_courses.append((score, course))
    matching_courses.sort(key=lambda item: (-item[0], item[1]["title"]))
    suggested_course = None
    if matching_courses:
        course = matching_courses[0][1]
        suggested_course = {"title": course["title"], "category": course["category"], "url": COURSE_URL}

    if not matched_skills and has_training_topic:
        matched_skills.append("Training or skill development")
    return {
        "request_type": request_type,
        "skills": matched_skills,
        "location": location,
        "asks_location": asks_location,
        "suggested_course": suggested_course,
        "is_direct_brand_request": mentions_tata_strive(text),
    }
