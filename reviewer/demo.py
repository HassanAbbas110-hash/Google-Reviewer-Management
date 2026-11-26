"""Fictional demo: a made-up business and a "try one review" helper.

`try_review` calls the exact same `make_draft` the live inbox uses, so a demo
result is what the live workflow would do. Nothing here touches Google.
"""
from reviewer.ai import make_draft
from reviewer.mock_google import DEMO_BUSINESS, DEMO_REVIEWS, MockGoogle

OLDER_REVIEWS = [('Bongani Z.', 5, 'Been coming here for years. Good people.'),
                 ('Kim L.', 4, 'Decent range of paint.')]
SAMPLES ={f'sample{i}': {'title': who, 'rating': stars, 'text': text} for i, (who, stars, text) in enumerate(DEMO_REVIEWS)}


def create_demo_business(db, mock: MockGoogle, actor='system'):
    """Create the fictional shop, connected to the fictional Google profile. Publishing starts off."""
    bid = db.save_business(dict(DEMO_BUSINESS), actor=actor)
    db.update_settings(bid, is_demo=1, location=mock.location(bid), connection_status='Demo', consent=1,
                       publish_mode='off', baseline_done=0)
    # Two reviews that "already existed" when the shop connected: they form the first-sync baseline
    # (one already has a reply on Google, which must be preserved).
    mock.seed(bid, OLDER_REVIEWS, existing_reply_for=(0,), prefix='older', days_ago=5)
    for review in mock.reviews(db.business(bid)):
        db.ingest(bid, review, baseline=True)
    db.update_settings(bid, baseline_done=1)
    # The test reviews arrive "after" connecting; the next sync picks them up as new.
    mock.seed(bid)
    db.audit(bid, None, actor, 'Demo created', 'Fictional business and reviews. Posts go to a local fake, never Google.')
    return bid


def try_review(business, ai, text, rating, recent=()):
    if type(rating) is not int or not 1 <= rating <= 5:
        raise ValueError('Choose a rating from 1 to 5.')
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError('Reviews can be at most 4,000 characters here.')
    return make_draft(ai, business, text, rating, recent)
