"""Local sparse text-vector ranking after deterministic eligibility filtering."""
from collections import Counter
import math
import re

from backend.eligibility_engine import evaluate_scheme_eligibility


def rank_schemes(schemes, profile, query=""):
    def tokens(text):
        return re.findall(r"[^\W_]+", text.casefold())
    texts = [" ".join(str(s.get(k, "")) for k in ("id", "name", "name_hi", "category", "target_group", "benefit", "benefit_hi")) for s in schemes]
    counts = [Counter(tokens(text)) for text in texts]
    query_counts = Counter(tokens(query))
    frequency = Counter(token for count in counts for token in count)
    def vector(count):
        result = {token: (1 + math.log(n)) * (1 + math.log((1 + len(counts)) / (1 + frequency[token]))) for token, n in count.items()}
        norm = math.sqrt(sum(v*v for v in result.values())) or 1
        return {token: value/norm for token, value in result.items()}
    q = vector(query_counts)
    ranked = []
    for scheme, count in zip(schemes, counts):
        eligibility = evaluate_scheme_eligibility(scheme, profile)
        if eligibility['status'] == 'NOT_ELIGIBLE':
            continue
        score = sum(value * q.get(token, 0) for token, value in vector(count).items())
        if query.strip() and not score:
            continue
        ranked.append({"scheme": scheme, "eligibility": eligibility, "score": round(score, 5)})
    return sorted(ranked, key=lambda item: (item['eligibility']['status'] != 'ELIGIBLE', -item['score']))
