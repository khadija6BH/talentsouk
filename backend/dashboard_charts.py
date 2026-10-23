"""Count-only dashboard chart payload; activity must belong to the signed-in user."""
from collections import Counter

def summarize_charts(companies, activity):
    counts = Counter(str(company.get('category') or 'Other').strip() or 'Other' for company in companies)
    categories = sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    distribution = categories[:5]
    remainder = sum(count for _, count in categories[5:])
    if remainder:
        distribution.append(('Other categories', remainder))
    return {'company': {'total': len(companies),
            'with_email': sum(bool(str(company.get('email') or '').strip()) for company in companies),
            'categories': categories[:10],
            'category_chart': [{'name':name, 'count':count} for name,count in distribution]},
            'activity': activity}
