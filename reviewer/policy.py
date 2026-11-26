"""Review classification, routing and publish eligibility.

One module, used by the live engine, the demo page and the test lab, so all
three always make the same decision. Classification ("what is this review?")
is kept separate from routing ("what do we do with it?") and from publish
eligibility ("may this exact reply be sent now?").

Reviewer text is untrusted data. Nothing in it can change these rules.
"""
from dataclasses import dataclass, field
import re

# ---------------------------------------------------------------- vocabulary
F = re.I | re.S

PRODUCT = (r'\b(?:batter(?:y|ies)|charger?s?|devices?|drills?|heaters?|kettles?|plugs?|'
           r'appliances?|equipment|tools?|vapes?|pods?|coils?|phones?|power ?banks?|'
           r'cables?|lead|extension|sockets?|machines?|e-?cig\w*|mods?|grinder|saw|'
           r'toaster|iron|fan|lamp|bulb|product|item|unit|thing|it)\b')
HAZARD = (r'\b(?:smok(?:e|es|ed|ing)|overheat\w*|over-heat\w*|spark(?:s|ed|ing)?\b|burn(?:ed|t|ing|s)?|'
          r'melt\w*|sizzl\w*|scorch\w*|hot to (?:the )?touch|swell\w*|swollen|'
          r'leak(?:ed|ing|s)? (?:acid|gas|liquid|chemicals?))')

# Each sensitive concern: (code, staff label, owner must be told?, patterns)
SENSITIVE = [
    ('safety', 'Possible product safety incident', True, [
        PRODUCT + r'\W+(?:\w+\W+){0,12}?' + HAZARD,
        HAZARD + r'\W+(?:\w+\W+){0,8}?' + PRODUCT,
        r'\b(?:caught|catch(?:es|ing)?|went up in|burst into) (?:on )?fire\b', r'\bon fire\b',
        r'\bexplod\w*|\bexplosion\b|\bblew up\b',
        r'\belectric(?:al|ity)? shock\b|\b(?:got|gave me) (?:a |an )?shock\b|\belectrocut\w*',
        r'\bgas leak\b|\bsmell(?:ed|s)? (?:of )?gas\b|\bcarbon monoxide\b',
        r'\bunsafe\b|\bdangerous\b|\bhazard(?:ous)?\b|\bfire risk\b',
        r'\binjur\w*|\bhurt (?:my|me|him|her|them|their)\b|\bcut (?:my|his|her) (?:hand|finger|arm|leg)\b|\bbleed\w*|\bblood\b',
        r'\bhospital\b|\bA&E\b|\bemergency room\b|\bER visit\b|\bambulance\b|\bstitches\b',
        r'\bfood poisoning\b|\bpoison\w*|\ballerg\w*|\banaphyla\w*|\b(?:got|was|became|felt) (?:really |very )?(?:sick|ill)\b(?! of)|\bvomit\w*|\bthrew up\b',
    ]),
    ('billing', 'Billing or payment dispute', True, [
        r'\bcharged (?:me )?(?:twice|two times|double|2 times|again)\b',
        r'\bdouble[- ]?(?:charg\w*|bill\w*|payment)', r'\b(?:billed|debited|paid) (?:me )?(?:twice|two times|double)\b',
        r'\bcharged (?:me )?(?:for something|without|the wrong amount|more than)\b',
        r'\bovercharg\w*', r'\bunauthori[sz]ed (?:charge|payment|transaction)\b',
        r'\brefund\w*', r'\bchargeback\b', r'\bmoney back\b', r'\b(?:money|payment|amount|charge|transaction)\W+(?:\w+\W+){0,4}?(?:twice|two times|double)\b',
        r'\b(?:still|never) (?:got|received|had) (?:my )?(?:money|payment|deposit)\b',
        r'\bdispute (?:the |this |a )?(?:charge|payment|transaction)\b',
        r'\bcard (?:was |got )?(?:charged|debited) (?:twice|two times|double)\b',
    ]),
    ('threat', 'Threat or legal action', True, [
        r'\blawyers?\b|\battorneys?\b|\bsolicitors?\b|\blawsuit\b|\bsu(?:e|ing) (?:you|them|the)\b|\blegal action\b|\b(?:take (?:you|them|this) to|see you in) court\b|\bsmall claims\b',
        r'\bpolice\b|\breport(?:ed|ing)? (?:you|them|this) to\b|\btrading standards\b|\bconsumer (?:council|commission|protection)\b|\bombudsman\b',
        r'\bkill\b|\bburn (?:it|the place|your shop) down\b|\bwatch your back\b|\byou.ll regret\b|\bcoming for you\b|\bhurt you\b',
    ]),
    ('allegation', 'Serious allegation', True, [
        r'\bfraud\w*|\bscam\w*|\bstole\b|\bstolen\b|\btheft\b|\bthie(?:f|ves|ving)\b|\bcon artists?\b|\bripped me off\b',
        r'\bdiscriminat\w*|\bracis\w*|\bsexis\w*|\bhomophob\w*|\btransphob\w*|\bbigot\w*',
        r'\bharass\w*|\bassault\w*|\bgrop\w*|\binappropriate(?:ly)? touch\w*|\bsexual\w*|\babus(?:e|ed|ive)\b|\bviolen\w*|\bthreaten\w*|\bhit me\b',
        r'\bdrunk\b|\bhigh on\b',
        r'\bcounterfeit\b|\bfake (?:products?|goods|items?|brand)\b|\bknock-?offs?\b',
        r'\bunder ?age\b|\bminors\b|\bsold (?:to )?(?:a |my )?(?:kid|child|teen\w*|\d{2} year old)\b',
        r'\bhealth (?:code|inspector|department)\b|\brats?\b|\bmice\b|\bcockroach\w*',
    ]),
    ('private_info', 'Contains personal or contact details', False, [
        r'https?://\S+|www\.\S+',
        r'[\w.+-]+@[\w-]+\.[\w.]{2,}',
        r'\+?\d[\d ()-]{7,}\d',
        r'\b(?:my )?(?:card|account|order|invoice|receipt|reference|ref|id) (?:number|no\.?|#)\s*[:#]?\s*\w*\d',
        r'\b\d{1,5} [A-Z][a-z]+ (?:Street|St|Road|Rd|Avenue|Ave|Lane|Drive|Dr)\b',
    ]),
    ('instructions', 'Contains instructions addressed to the reply system', False, [
        r'\b(?:ignore|disregard|forget|override|bypass)\s+(?:(?:all|any|your|the|previous|prior|above|earlier|of|these|those|my)\s+)*(?:instructions?|prompts?|rules|guidelines|programming|system)\b',
        r'\bsystem prompt\b|\bprompt injection\b|\bjailbreak\b|\bdeveloper mode\b',
        r'\b(?:you are|you.re|as) (?:an? )?(?:AI|bot|language model|LLM|chatgpt)\b',
        r'\b(?:promise|guarantee|confirm|tell|offer) (?:me|us)\b\W+(?:\w+\W+){0,6}?(?:free|refund|replacement|discount|voucher|compensation|money)\b',
        r'\b(?:please |you must |you should |now )(?:reply|respond|write|say|answer)\b',
        r'\bnew instructions?\b',
    ]),
]

# Ordinary complaints: (code, label for staff, words the reply must touch)
COMPLAINT = [
    ('wait', 'Waiting time', r'wait|queue|delay|slow|time|long|quick|fast|ages|line', [
        r'\bwait(?:ed|ing)?\b(?!\s+(?:for (?:it|the) (?:to )?(?:arrive|delivery)))',
        r'\b(?:took|takes|taking) (?:ages|forever|so long|too long|a long time|an hour|hours)\b',
        r'\bslow\w*|\bqueue\w*|\bdelay\w*|\blate\b|\bages to\b|\bforever to\b|\bhalf an hour\b|\blong line\b',
    ]),
    ('staff', 'Staff attitude or service', r'service|staff|team|help|treated|experience|attitude|visit|concern|feedback|welcom|happened|came in', [
        r'\brude\w*|\bunhelpful\b|\bunfriendly\b|\bimpolite\b|\bdismissive\b|\barrogant\b|\bcondescending\b|\bignored (?:me|us)\b',
        r'\bno one (?:helped|came|was around)\b|\bnobody (?:helped|came|was around)\b|\bcouldn.t find anyone\b|\bbad attitude\b|\bunprofessional\b',
        r'\bpoor (?:service|customer service)\b|\bbad (?:service|customer service)\b|\bterrible service\b|\bawful service\b|\bdidn.t (?:care|help)\b|\bwasn.t helpful\b',
    ]),
    ('product', 'Product fault or quality', r'stop|work|broke|fault|issue|problem|quality|product|drill|item|order|tool|defect', [
        r'\bstopped working\b|\bdoesn.t work\b|\bdidn.t work\b|\bdoes not work\b|\bdid not work\b|\bnot working\b|\bwon.t (?:work|turn on|charge)\b',
        r'\bbroke\b|\bbroken\b|\bfaulty\b|\bdefective\b|\bdamaged\b|\bcracked\b|\bfell apart\b|\bpoor quality\b|\bcheap(?:ly)? made\b|\bdud\b|\bleak(?:s|ed|ing)?\b',
    ]),
    ('wrong_item', 'Wrong or missing item', r'wrong|missing|order|item|size|mix', [
        r'\bwrong (?:\w+ )?(?:item|size|order|part|product|colou?r|one|screws?|bolts?|model)\b|\bgot the wrong\b|\bgave me the wrong\b',
        r'\bmissing (?:items?|parts?|pieces?)\b|\bincomplete order\b|\bnot what I ordered\b',
    ]),
    ('price', 'Price concern', r'price|pric|cost|expensive|value', [
        r'\b(?:over ?priced|too expensive|very expensive|so expensive|pricey|rip-?off|daylight robbery)\b',
    ]),
    ('parking', 'Parking or access', r'park', [
        r'\bparking\b\W+(?:\w+\W+){0,6}?(?:difficult|tricky|hard|problem\w*|limited|bad|poor|nightmare|impossible|a pain|terrible|awful|full|non-existent)',
        r'\b(?:difficult|tricky|hard|limited|no|impossible|terrible|awful) parking\b|\bhard to park\b|\bnowhere to park\b|\bcouldn.t (?:find )?park\w*',
    ]),
    ('cleanliness', 'Cleanliness', r'clean|tidy|mess|dirty|state|smell', [
        r'\bdirty\b|\bfilthy\b|\bmessy\b|\buntidy\b|\bsmell(?:y|s|ed)\b|\bstink\w*',
    ]),
    ('stock', 'Availability', r'stock|availab|have|range|sold', [
        r'\bout of stock\b|\bsold out\b|\bdidn.t have (?:it|what|the)\b|\bdon.t (?:stock|carry)\b|\bnever (?:in stock|have)\b',
    ]),
    ('unresolved', 'Earlier complaint not resolved', r'complain|concern|resolv|address|follow|hear|respon|issue|still', [
        r'\bno complaints? (?:were|was|are|is|have been|has been|got|get|being) (?:\w+ )?(?:addressed|resolved|answered|handled|taken|dealt)',
        r'\b(?:complaint|issue|problem|query|email) (?:is |was |remains |still )*(?:still )?(?:unresolved|ignored|unanswered|not (?:resolved|addressed|answered))\b',
        r'\bnever (?:called|got|heard|emailed|wrote) (?:me )?back\b|\bno (?:reply|response|answer) (?:to|from)\b|\bstill (?:waiting|unresolved)\b',
    ]),
    ('general', 'General dissatisfaction', r'sorry|feedback|experience|disappoint|expect|hear|let you down|missed the mark|not what', [
        r'\bdisappoint\w*|\bterrible\b|\bawful\b|\bhorrible\b|\bworst\b|\bappalling\b|\bdisgrace\w*|\bunacceptable\b|\bpathetic\b|\buseless\b',
        r'\bnot (?:happy|impressed|great|good|ideal|worth)\b|\bunhappy\b|\bnever again\b|\bwon.t (?:be )?(?:back|return\w*|coming back)\b|\bavoid\b|\bwaste of\b|\bmediocre\b|\bcould (?:be|have been) better\b|\blet (?:me|us) down\b',
        r'\b(?:bad|poor|frustrat\w*|annoy\w*|hassle|problem|issue|complain\w*|difficult|wrong|lacking)\b',
    ]),
]

# Phrases that look negative but are praise; removed before complaint matching.
NEGATED_POSITIVE = [
    r'\b(?:no|zero|never (?:any|a)|without (?:any|a)|not (?:a|one) single|not one|nothing but|no real) (?:complaints?|problems?|issues?|hassle|fuss|wait(?:ing)?|queues?|delays?|bad words?)\b'
    r'(?!\s+(?:were|was|are|is|have|has|had|got|get|being)\b)',
    r'\bnot (?:bad|too bad|slow|expensive|rude|difficult|a problem|an issue|disappointed|disappointing)\b',
    r'\b(?:can.t|cannot|couldn.t|could not) (?:fault|complain|be faulted)\b',
    r'\bno need to wait\b|\bwithout waiting\b|\bdidn.t (?:have to )?wait\b|\bno wait\b|\bwasn.t (?:a )?long wait\b',
    r'\bno problem\b|\bnothing (?:was )?(?:too much|a problem)\b|\bproblem solved\b|\bsolved (?:my|the) (?:problem|issue)\b|\bfixed (?:my|the) (?:problem|issue)\b',
    r'\b(?:helped|help|sorted|fixed) (?:me )?(?:out )?(?:with )?(?:my|a|an|the) (?:problem|issue)\b',
    r'\b(?:can.t|cannot|couldn.t) wait\b|\bworth the wait\b|\bopen late\b|\bnothing but\b|\bcan.t go wrong\b|\bnothing (?:went )?wrong\b',
    r'\bsmoking area\b|\bsmoke[- ]free\b|\bvape (?:juice|liquid)s?\b',
]
CONTRAST = r'\b(?:but(?! also\b)|however|although|though|except|apart from|other than|only (?:issue|problem|downside|thing|complaint|gripe)|shame|pity|unfortunately|wish|if only|would be nice|could do with)\b'
POSITIVE = (r'\b(?:great|good|excellent|amazing|awesome|fantastic|brilliant|lovely|love[d]?|friendly|helpful|'
            r'kind|clean|tidy|quick|fast|easy|perfect(?:ly)?|best|recommend\w*|thank\w*|thanks|knowledgeable|professional|'
            r'fair|welcoming|patient|efficient|happy|pleased|wonderful|superb|outstanding|nice|polite|cheap|'
            r'affordable|reasonable|spot on|well done|top|five stars?|5 stars?|fits?|sorted|appreciate\w*|no complaints?(?!\s+(?:were|was|are|is|have|has|got|being)\b))\b')

OWNER_CONCERNS = {code for code, _, owner, _ in SENSITIVE if owner}
_SENSITIVE = [(c, l, o, [re.compile(p, F) for p in ps]) for c, l, o, ps in SENSITIVE]
_COMPLAINT = [(c, l, re.compile(r'\b(?:' + k + ')', re.I), [re.compile(p, F) for p in ps]) for c, l, k, ps in COMPLAINT]
_NEGATED = [re.compile(p, F) for p in NEGATED_POSITIVE]
_CONTRAST = re.compile(CONTRAST, re.I)
_POSITIVE = re.compile(POSITIVE, re.I)
MAX_TEXT = 4000


@dataclass
class Classification:
    category: str            # routine | rating_only | mixed | complaint | sensitive | uncertain
    rating: int
    concerns: list = field(default_factory=list)  # [{'code','label','sensitive','owner'}]
    positive: bool = False
    confident: bool = False  # strong enough evidence for (optional) automatic publishing
    reason: str = ''         # short staff-facing explanation, never shown publicly

    @property
    def codes(self):
        return [c['code'] for c in self.concerns]

    def as_dict(self):
        return {'category': self.category, 'rating': self.rating, 'concerns': self.concerns,
                'positive': self.positive, 'confident': self.confident, 'reason': self.reason}


def _clean(text):
    text = str(text or '')
    text = re.sub(r'[‘’ʼ]', "'", text)
    text = re.sub(r'[–—]', ' - ', text)
    return text


def classify(text, rating):
    """Classify the written content first; the star rating never hides a concern."""
    if type(rating) is not int or not 1 <= rating <= 5:
        raise ValueError('Rating must be a whole number from 1 to 5')
    text = _clean(text)
    stripped = text.strip()
    concerns = []

    if len(stripped) > MAX_TEXT:
        return Classification('uncertain', rating, [], reason='Review is unusually long; staff should read it in full.')

    for code, label, owner, patterns in _SENSITIVE:
        if any(p.search(text) for p in patterns):
            concerns.append({'code': code, 'label': label, 'sensitive': True, 'owner': owner})

    softened = text
    for p in _NEGATED:
        softened = p.sub(' ', softened)
    for code, label, _, patterns in _COMPLAINT:
        if any(p.search(softened) for p in patterns):
            if code == 'general' and any(not c['sensitive'] for c in concerns):
                continue  # a specific concern already explains the negativity
            concerns.append({'code': code, 'label': label, 'sensitive': False, 'owner': False})

    positive = bool(_POSITIVE.search(text))
    sensitive = [c for c in concerns if c['sensitive']]
    ordinary = [c for c in concerns if not c['sensitive']]

    if sensitive:
        labels = ', '.join(c['label'].lower() for c in sensitive)
        return Classification('sensitive', rating, concerns, positive, False,
                              f'Hold for staff: {labels}. No AI public reply.')
    if not stripped:
        if rating >= 4:
            return Classification('rating_only', rating, [], False, True, f'{rating}-star rating with no comment.')
        return Classification('complaint', rating, [{'code': 'low_rating', 'label': 'Low rating without a comment',
                                                     'sensitive': False, 'owner': False}],
                              reason=f'{rating}-star rating with no comment; staff should check the reply.')
    if ordinary:
        labels = ', '.join(c['label'].lower() for c in ordinary)
        if positive and rating >= 3:
            return Classification('mixed', rating, concerns, True, False, f'Mixed: praise plus {labels}.')
        return Classification('complaint', rating, concerns, positive, False, f'Complaint: {labels}.')
    contrast = _CONTRAST.search(softened)
    if contrast:
        return Classification('uncertain', rating, [], positive, False,
                              f'Possible concern after "{contrast.group(0)}"; staff should check.')
    if rating <= 2:
        return Classification('uncertain', rating, [], positive, False,
                              f'{rating}-star rating but no clear concern in the text; staff should check.')
    if rating == 3:
        return Classification('mixed', rating, [], positive, False, 'Three stars: lukewarm; staff should check the reply.')
    return Classification('routine', rating, [], positive, positive,
                          'Positive review.' if positive else 'No concern found; wording is neutral.')


# ------------------------------------------------------------------- routing
@dataclass
class Route:
    action: str          # draft | approve | hold
    ai_draft: bool       # may a model write the public draft?
    quick_reply: bool    # a deterministic reply is available, no model needed
    investigation: bool  # opens a case
    owner_alert: bool    # owner / designated contact must be told
    auto_eligible: bool  # may be considered for automatic publishing (if business opted in)
    label: str           # short queue label for staff


def route(cls: Classification) -> Route:
    if cls.category == 'sensitive':
        owner = any(c['owner'] for c in cls.concerns)
        return Route('hold', False, False, True, owner, False,
                     'Held for staff investigation' + (' and owner' if owner else ''))
    if cls.category == 'rating_only':
        return Route('draft', False, True, False, False, True, 'Rating only')
    if cls.category == 'routine':
        return Route('draft', True, False, False, False, cls.confident, 'Routine praise')
    if cls.codes == ['low_rating']:
        return Route('approve', False, True, False, False, False, 'Low rating, needs staff approval')
    label = {'mixed': 'Mixed feedback', 'complaint': 'Complaint', 'uncertain': 'Unclear, needs staff check'}[cls.category]
    return Route('approve', True, False, False, False, False, label + ', needs staff approval')


def combine(cls: Classification, model_category: str) -> Classification:
    """A model may escalate the rule result, never downgrade it."""
    order = ['rating_only', 'routine', 'uncertain', 'mixed', 'complaint', 'sensitive']
    if model_category not in order or order.index(model_category) <= order.index(cls.category):
        return cls
    if model_category == 'sensitive':
        cls.concerns.append({'code': 'model_flag', 'label': 'Model flagged a possible serious issue',
                             'sensitive': True, 'owner': False})
        return Classification('sensitive', cls.rating, cls.concerns, cls.positive, False,
                              'Hold for staff: the model flagged a possible serious issue.')
    if cls.category in ('routine', 'rating_only'):
        return Classification('uncertain', cls.rating, cls.concerns, cls.positive, False,
                              'The model saw a possible concern; staff should check.')
    return cls


# ------------------------------------------------------------- quick replies
def quick_reply(business, cls: Classification, recent=()):
    """Deterministic, model-free replies for comment-free ratings.

    Never infers a visit, purchase or product. Picks a phrasing that does not
    repeat the opening of the business's recent replies.
    """
    name = (business.get('name') or '').strip()
    sign = (business.get('sign_off') or '').strip()
    if cls.category == 'rating_only':
        options = ['Thanks so much for the {r} stars!', 'Thank you for the {r}-star rating, it means a lot.',
                   'Really appreciate the {r} stars, thank you!', 'Thanks for taking a moment to rate us!']
    else:
        contact = first_channel(business)
        tail = f' If you are happy to tell us what went wrong at {contact}, we would like to hear it.' if contact else \
            ' If you are happy to share what went wrong, we would like to hear it.'
        options = ['Sorry we missed the mark.' + tail, 'Thanks for the rating, and sorry it was not a better one.' + tail]
    used = {str(r or '').split(' ')[0].lower() for r in recent}
    choice = next((o for o in options if o.split(' ')[0].lower() not in used), options[0])
    reply = choice.format(r=cls.rating)
    if sign:
        reply += ' ' + sign
    return reply


CHANNEL = re.compile(r'https?://[^\s<>]+|[\w.+-]+@[\w-]+\.[\w.-]+\w|\+?\d[\d ()-]{6,}\d')


def channels(business):
    """Approved public contact channels (exact strings)."""
    raw = (business.get('contact') or '')
    return [m.group(0).strip() for m in CHANNEL.finditer(raw)]


def first_channel(business):
    found = channels(business)
    return found[0] if found else ''


# ---------------------------------------------------------- publish checking
def publish_blockers(business, job, *, paused, automatic=False, expected_hash=None):
    """Every reason this exact reply must not be sent now. Empty list = allowed.

    Called server-side at the moment of sending, not only when a page renders.
    """
    from reviewer.text import digest
    out = []
    mode = business.get('publish_mode') or 'off'
    if paused:
        out.append('All publishing is paused.')
    if mode == 'off':
        out.append('Publishing is off for this business (draft-only).')
    if automatic and mode not in AUTO_MODES:
        out.append('Automatic publishing is not enabled for this business.')
    if not business.get('consent'):
        out.append('The owner has not authorised WebRift to publish replies.')
    if not business.get('location'):
        out.append('No Google location is connected.')
    if business.get('connection_status') not in ('Connected', 'Demo'):
        out.append('The Google connection needs attention: ' + str(business.get('connection_status')))
    if job.get('status') != 'approved':
        out.append('The reply is not approved.')
    draft = job.get('draft') or ''
    if not draft.strip():
        out.append('There is no reply text.')
    if job.get('approved_hash') != digest(draft):
        out.append('The reply changed after approval. Approve it again.')
    if expected_hash is not None and expected_hash != job.get('approved_hash'):
        out.append('The reply on screen is not the approved reply. Reload and check it.')
    if job.get('approved_fingerprint') != job.get('fingerprint'):
        out.append('The review changed after approval. Check it and approve again.')
    if int(job.get('approved_version') or -1) != int(business.get('version') or 0):
        out.append('Business details changed after approval. Approve again.')
    if job.get('category') == 'sensitive' and job.get('draft_source') not in ('staff',):
        out.append('Sensitive reviews need a staff-written reply.')
    if job.get('issues_hard'):
        out.append('The reply failed a safety check: ' + job['issues_hard'])
    if automatic:
        allowed = auto_categories(mode)
        if job.get('category') not in allowed or (job.get('category') == 'routine' and not job.get('auto_eligible')):
            out.append('This kind of review is not set to reply automatically.')
        if not business.get('facts_approved'):
            out.append('Business facts have not been checked.')
        if job.get('draft_source') not in ('ai', 'quick'):
            out.append('Automatic publishing only sends unedited system drafts.')
        if job.get('issues_soft'):
            out.append('The draft has a style note, so a person should look at it.')
        if job.get('baseline'):
            out.append('Reviews from before the first sync are never published automatically.')
    return out


AUTO_MODES = ('auto', 'auto_most')


def auto_categories(mode):
    """What each automatic level may answer on its own. Sensitive and unclear: never."""
    if mode == 'auto':
        return ('routine', 'rating_only')
    if mode == 'auto_most':
        return ('routine', 'rating_only', 'mixed', 'complaint')
    return ()
