"""Reports. Monthly = this app's own activity events. Weekly = the inbox right now plus this week's reviews."""
from datetime import datetime, timedelta, timezone
import re


def monthly_report(db, bid, month):
    if not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('Use a month in YYYY-MM format')
    start = datetime.strptime(month, '%Y-%m').replace(tzinfo=timezone.utc)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    result = {'month': month, 'published': 0, 'needs_approval': 0, 'failed': 0, 'investigations_opened': 0}
    with db.connect() as c:
        for row in c.execute('SELECT action,COUNT(*) AS n FROM events WHERE business_id=? AND occurred>=? AND occurred<? GROUP BY action',
                             (bid, start.timestamp(), end.timestamp())):
            result[row['action']] = row['n']
    return result


def week_bounds(week=None):
    """Monday 00:00 UTC of the given ISO date's week (default: this week)."""
    day = datetime.strptime(week, '%Y-%m-%d').replace(tzinfo=timezone.utc) if week else datetime.now(timezone.utc)
    start = (day - timedelta(days=day.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def _created(job):
    try:
        return datetime.fromisoformat(job['created'].replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def weekly_report(db, bid=None, week=None):
    if week and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week):
        raise ValueError('Use a date in YYYY-MM-DD format')
    start, end = week_bounds(week)
    businesses = [db.business(bid)] if bid else db.businesses()
    rows = []
    for b in businesses:
        jobs = db.jobs(b['id'])
        this_week = [j for j in jobs if (_created(j) or datetime.min.replace(tzinfo=timezone.utc)) >= start
                     and (_created(j) or end) < end]
        ratings = {n: sum(1 for j in this_week if j['rating'] == n) for n in range(5, 0, -1)}
        rated = [j['rating'] for j in this_week if j['rating']]
        rows.append({
            'business': b,
            'volume': len(this_week),
            'ratings': ratings,
            'average': round(sum(rated) / len(rated), 2) if rated else None,
            'pending': sum(1 for j in jobs if j['status'] in ('new', 'drafting', 'needs_review', 'approved', 'failed')),
            'approved_unpublished': sum(1 for j in jobs if j['status'] == 'approved'),
            'investigations': sum(1 for j in jobs if j['investigation'] in ('open', 'in_progress')),
            'failures': sum(1 for j in jobs if j['status'] in ('failed', 'publish_unknown') or (j['error'] and j['status'] == 'approved')),
            'alerts_failed': sum(1 for a in db.alerts(b['id'], open_only=True) if a['state'] == 'failed'),
            'published_week': sum(1 for j in jobs if start.timestamp() <= (j['published_at'] or 0) < end.timestamp()),
        })
    totals = {k: sum(r[k] for r in rows) for k in ('volume', 'pending', 'investigations', 'failures', 'alerts_failed', 'published_week')}
    totals['ratings'] = {n: sum(r['ratings'][n] for r in rows) for n in range(5, 0, -1)}
    return {'start': start.date().isoformat(), 'end': (end - timedelta(days=1)).date().isoformat(),
            'prev': (start - timedelta(days=7)).date().isoformat(), 'next': end.date().isoformat(),
            'rows': rows, 'totals': totals}
