"""Own operational events only: no Google review text, ratings or identifiers."""
from datetime import datetime,timezone
import re


def monthly_report(db,bid,month):
    if not re.fullmatch(r'\d{4}-\d{2}',month): raise ValueError('Use a month in YYYY-MM format')
    start=datetime.strptime(month,'%Y-%m').replace(tzinfo=timezone.utc)
    end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
    result={'month':month,'published':0,'needs_approval':0,'failed':0,'investigations_opened':0}
    with db.connect() as c:
        for row in c.execute('SELECT action,COUNT(*) AS n FROM events WHERE business_id=? AND occurred>=? AND occurred<? GROUP BY action',(bid,start.timestamp(),end.timestamp())):
            result[row['action']]=row['n']
    return result
