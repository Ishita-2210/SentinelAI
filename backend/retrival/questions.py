"""Deterministic bounded question filters; timestamps never supplied by an LLM."""
from datetime import datetime,timedelta,timezone
import re
WORDS={"one":1,"two":2,"three":3,"five":5,"ten":10,"fifteen":15,"thirty":30,"sixty":60}
def question_filters(question, now=None, limit=20):
    text=question.lower()
    result={"limit":limit}
    mapping=[("unattended","UNATTENDED_OBJECT"),("loiter","LOITERING"),
             ("running","RUNNING"),("entered","PERSON_ENTERED"),
             ("entry","PERSON_ENTERED"),("exited","PERSON_EXITED"),("zone changed","ZONE_CHANGED")]
    for phrase,kind in mapping:
        if phrase in text:
            result["event_type"]=kind;break
    ident=re.search(r"(?:event\s*(?:id\s*)?|#)(\d+)\b",text)
    if ident:result["event_id"]=int(ident.group(1))
    if "vlm" in text or "verification result" in text:
        result["with_vlm"]=True
    stamp=re.search(r"\d{4}-\d{2}-\d{2}[tT ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?",question)
    if "around" in text:
        if not stamp:raise ValueError("Include an ISO timestamp with timezone, for example 2026-10-20T10:00:00+05:30")
        dt=datetime.fromisoformat(stamp.group().replace("Z","+00:00"))
        if dt.tzinfo is None:raise ValueError("Around-time queries require a timezone offset")
        result.update(start=(dt-timedelta(minutes=2)).isoformat(),end=(dt+timedelta(minutes=2)).isoformat())
    recent=re.search(r"last\s+(\d+|one|two|three|five|ten|fifteen|thirty|sixty)\s+(seconds?|minutes?|hours?)",text)
    if recent:
        count=WORDS.get(recent.group(1),int(recent.group(1)) if recent.group(1).isdigit() else 0)
        seconds=count*(3600 if recent.group(2).startswith("hour") else 60 if recent.group(2).startswith("minute") else 1)
        if seconds>7*86400:raise ValueError("Time window must not exceed seven days")
        now=now or datetime.now(timezone.utc)
        result.update(start=(now-timedelta(seconds=seconds)).isoformat(),end=now.isoformat())
    if ("latest" in text or "when was the last" in text) and "summar" not in text:
        result["limit"]=1
    return result
