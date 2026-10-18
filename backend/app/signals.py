"""Explainable fallback signals for records without a validated local LLM result."""
from collections import Counter
import re

from vader_sentiment.vader_sentiment import SentimentIntensityAnalyzer

_vader = SentimentIntensityAnalyzer()
_STOP = set("a an and are as at be been but by for from had has have he her hers him his i if in into is it its me my of on or our ours she so that the their them there they this to us was we were what when where which who will with you your tata strive tatastrive https http com www instagram linkedin reddit youtube google".split())
_URGENT = {"urgent", "unsafe", "danger", "scam", "fraud", "harassment", "injury", "safety", "immediately", "emergency"}
_COMPLAINT = {"bad", "broken", "issue", "problem", "complaint", "disappointed", "delay", "failed", "poor", "wrong", "unhelpful", "refund"}
_PRAISE = {"great", "excellent", "amazing", "thank", "thanks", "helpful", "love", "good", "wonderful", "congratulations"}
_TOPICS = {
    "training and courses": {"training", "course", "courses", "skill", "skills", "program", "programme", "learn", "learning"},
    "jobs and placement": {"job", "jobs", "placement", "career", "employment", "employability", "hiring", "work"},
    "enrollment and access": {"apply", "application", "admission", "enroll", "enrollment", "register", "registration", "eligibility"},
    "support and experience": {"support", "help", "experience", "issue", "problem", "complaint", "feedback"},
}
_AUDIENCE_RULES = (
    ("employer_workforce", re.compile(r"\b(we are hiring|we're hiring|as an employer|our company|our factory|our workforce|we need (more |skilled |trained )?workers|looking to hire|skills gap|talent demand|technicians needed|vacancies)\b", re.I), 0.78),
    ("ecosystem_partner", re.compile(r"\b(we are an ngo|we're an ngo|our ngo|our foundation|our university|our college|we represent|seeking partners|looking for partners|partnership with|csr team|training provider)\b", re.I), 0.76),
    ("job_seeker", re.compile(r"\b(job seeker|jobseeker|looking for (a )?job|seeking employment|i need (a )?job|need help with (my )?(resume|cv)|i am searching for (a )?job|looking for an internship)\b", re.I), 0.78),
    ("learner", re.compile(r"\b(i am a student|i'm a student|as a student|i am a learner|i want to learn|i need training|looking for (a )?(course|training)|where can i (learn|train)|course for me|student enquiry|learner enquiry)\b", re.I), 0.76),
    ("community_supporter", re.compile(r"\b(i am a parent|i'm a parent|as a parent|i am a teacher|i'm a teacher|as a mentor|my child|my students)\b", re.I), 0.68),
    ("skills_audience_interest", re.compile(r"\b(course|training|skill development|vocational training|employability|job readiness|career guidance|placement)\b", re.I), 0.52),
)

# These rules recognize age groups explicitly discussed in the conversation.
# They must not be used to infer the age of an account or its author.
_AGE_GROUP_RULES = (
    ("under_18_explicit", re.compile(r"\b(under\s*18|below\s*18|underage|minor(s)?|teen(age(r|rs)?)?|adolescent(s)?|children|child labour)\b", re.I)),
    ("18_24_explicit", re.compile(r"\b(18\s*(?:-|to)\s*24|18\s*to\s*24|19\s*(?:-|to)\s*24|young adults? aged 18|in (?:their )?early twenties|\b2[0-4]-year-old)\b", re.I)),
    ("25_34_explicit", re.compile(r"\b(25\s*(?:-|to)\s*34|25\s*to\s*34|in (?:their )?late twenties|in (?:their )?early thirties|\b3[0-4]-year-old)\b", re.I)),
    ("35_plus_explicit", re.compile(r"\b(35\s*\+|35 and (?:above|over)|over 35|above 35|35-year-old|40-year-old|50-year-old|older adults?)\b", re.I)),
    ("youth_age_unspecified", re.compile(r"\b(youth|young people|young person)\b", re.I)),
)


def explicit_audience_mentions(text: str) -> dict[str, list[str]]:
    """Extract only clearly stated age-group and known-place mentions from text."""
    age_groups = [name for name, pattern in _AGE_GROUP_RULES if pattern.search(text)]
    # Use the same curated Indian place vocabulary as training-opportunity
    # extraction. Keep this import local to avoid a module import cycle.
    from app.opportunities import _extract_location

    place = _extract_location(text)
    places = [place] if place and place.casefold() != "near me" else []
    return {"age_groups": age_groups, "locations": places}


def infer_audience(text: str) -> dict[str, str | float]:
    """Infer the conversation's likely audience need, never the author's identity."""
    audience_segment, confidence = "unclear", 0.35
    for segment, pattern, score in _AUDIENCE_RULES:
        if pattern.search(text):
            audience_segment, confidence = segment, score
            break

    if re.search(r"\b(fee|fees|scholarship|admission|apply|application|eligib|enrol|enroll|register|registration)\b", text, re.I):
        need = "enrolment_access"
    elif re.search(r"\b(interview|resume|cv|placement|internship|job search|looking for (a )?job|job seeker)\b", text, re.I):
        need = "job_search_support"
    elif re.search(r"\b(hiring|workforce|skills gap|technicians needed|vacancies|talent demand)\b", text, re.I):
        need = "workforce_skills"
    elif re.search(r"\b(partner|partnership|collaborat|csr|grant|ngo|foundation)\b", text, re.I):
        need = "partnership"
    elif re.search(r"\b(course|training|skill|learn|course catalogue|centre|center)\b", text, re.I):
        need = "training_guidance"
    elif re.search(r"\b(unsafe|scam|fraud|harassment|injury|safety|complaint|problem|issue|disappointed)\b", text, re.I):
        need = "experience_or_safety"
    elif audience_segment == "unclear":
        need = "unclear"
    else:
        need = "general_guidance"

    pain_points = []
    pain_rules = (
        ("fees_and_affordability", r"\b(fee|fees|cost|price|afford|scholarship|free course)\b"),
        ("enrolment_and_eligibility", r"\b(admission|apply|application|eligib|enrol|enroll|register|registration)\b"),
        ("location_and_access", r"\b(near me|where|location|centre|center|transport|hostel|accommodation)\b"),
        ("course_and_skill_choice", r"\b(which course|what course|course for|skill should|what should i learn)\b"),
        ("language_access", r"\b(language|tamil|hindi|english|speak|medium of instruction)\b"),
        ("job_search_and_interviews", r"\b(interview|resume|cv|job search|looking for (a )?job|internship)\b"),
        ("placement_expectations", r"\b(placement|job guarantee|salary|employment after|job after)\b"),
        ("programme_experience", r"\b(experience|issue|problem|complaint|disappointed|delay|unhelpful)\b"),
        ("safety_and_trust", r"\b(unsafe|scam|fraud|harassment|injury|safety|misleading)\b"),
        ("workforce_skill_demand", r"\b(hiring|workforce|skills gap|technicians needed|vacancies|talent demand)\b"),
        ("partnership_fit", r"\b(partner|partnership|collaborat|csr|grant|ngo|foundation)\b"),
    )
    for point, pattern in pain_rules:
        if re.search(pattern, text, re.I):
            pain_points.append(point)
    emotion = "unclear"
    if re.search(r"\b(unsafe|scam|fraud|harassment|emergency|danger)\b", text, re.I):
        emotion = "concern_or_safety"
    elif re.search(r"\b(disappointed|angry|frustrat|unhelpful|poor|bad experience)\b", text, re.I):
        emotion = "frustration"
    elif re.search(r"\b(worried|confused|uncertain|afraid|nervous|anxious)\b", text, re.I):
        emotion = "uncertainty"
    elif re.search(r"\b(hope|excited|looking forward|interested|want to learn)\b", text, re.I):
        emotion = "interest_or_aspiration"
    elif re.search(r"\b(thank|thanks|helpful|great|excellent|amazing|love)\b", text, re.I):
        emotion = "appreciation"
    elif re.search(r"\b(please help|need help|can you help|how do i)\b", text, re.I):
        emotion = "help_seeking"
    return {"audience_segment": audience_segment, "audience_need": need,
            "audience_confidence": confidence, "pain_points": pain_points,
            "conversation_emotion": emotion}


def keyword_counts(text: str, limit: int = 5) -> list[dict[str, int | str]]:
    words = re.findall(r"[a-z][a-z0-9'-]{2,}", text.casefold())
    counts = Counter(word for word in words if word not in _STOP and not word.startswith("http"))
    return [{"term": word, "count": count} for word, count in counts.most_common(limit)]


def analyze_signals(source: str, record_type: str, text: str) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Cannot analyze empty content")
    words = set(re.findall(r"[a-z]+", text.casefold()))
    exact_brand = bool(re.search(r"\btata[\s-]+strive\b|#tatastrive", text, re.I))
    topic_scores = [(sum(term in words for term in terms), name) for name, terms in _TOPICS.items()]
    topic_score, topic = max(topic_scores)
    if not topic_score:
        topic = "general mention"
    relevance_type = "direct_brand" if exact_brand else "industry" if topic_score else "unrelated"
    scores = _vader.polarity_scores(text)
    sentiment = "positive" if scores["compound"] >= .05 else "negative" if scores["compound"] <= -.05 else "neutral"
    if "?" in text:
        intent = "question"
    elif words & _COMPLAINT:
        intent = "complaint"
    elif words & _PRAISE:
        intent = "praise"
    elif any(token in words for token in {"should", "suggest", "please", "could", "recommend"}):
        intent = "suggestion"
    else:
        intent = "discussion"
    repeated = keyword_counts(text)
    audience = infer_audience(text)
    urgency = bool(words & _URGENT)
    importance = min(100, 15 + (35 if exact_brand else 0) + (35 if urgency else 0) + (20 if intent == "complaint" else 0) + (10 if sentiment == "negative" else 0) + min(10, max(0, len(repeated) and repeated[0]["count"] - 1)))
    priority = "high" if importance >= 70 else "medium" if importance >= 40 else "low"
    terms = ", ".join(f"{item['term']} ×{item['count']}" for item in repeated) or "none detected"
    rationale = f"Estimated with VADER sentiment and keyword rules; priority score {importance}/100. Repeated terms: {terms}. Search previews are estimates from snippets." if record_type == "search_result" else f"Estimated with VADER sentiment and keyword rules; priority score {importance}/100. Repeated terms: {terms}."
    return {
        "is_relevant": relevance_type != "unrelated", "relevance_type": relevance_type,
        "topic": topic, "intent": intent, "sentiment": sentiment,
        "perception_signal": "Urgent language detected" if urgency else f"Sentiment score {scores['compound']:+.2f}",
        "confidence": 0.76 if exact_brand else 0.62 if relevance_type == "industry" else 0.35, "priority": priority, "rationale": rationale,
        "signal_model": "vader-rules-v1", "sentiment_score": scores["compound"],
        "importance_score": importance, "keyword_counts": repeated,
        **audience,
    }
