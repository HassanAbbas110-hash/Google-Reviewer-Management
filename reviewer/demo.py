"""Ephemeral local-model tests. No Google adapter, database writes or alerts."""
from reviewer.ai import assess,validate_output,combine_risk

SAMPLES={
 'praise':{'title':'Happy customer','rating':5,'text':'The team helped me find the right tools for my project. Friendly service and a clean shop. Thank you!'},
 'complaint':{'title':'Service complaint','rating':2,'text':'I waited a long time for help and the staff were rude when I asked about paint. Disappointing service.'},
 'sensitive':{'title':'Needs staff investigation','rating':1,'text':'I was charged twice for my order and need someone to investigate this.'},
 'rating-only':{'title':'Rating without a comment','rating':5,'text':''},
}


def generate_demo(business,ai,text,rating):
    if not business['facts_approved']: raise ValueError('Approve the business facts in publishing controls before testing replies.')
    if not business['model']: raise ValueError('Save an installed local Ollama model name in business settings first.')
    if type(rating) is not int or not 1<=rating<=5: raise ValueError('Choose a rating from 1 to 5.')
    if not isinstance(text,str) or len(text)>6000: raise ValueError('Sample review must be at most 6,000 characters.')
    risk=assess(text,rating)
    if risk=='sensitive':
        return {'risk':risk,'reply':'','reason':'Sensitive content: the live workflow would hold this for a staff-written reply and investigation. No AI reply was generated.','status':'held'}
    output=ai.generate(business,{'comment':text,'rating':rating})
    risk=combine_risk(risk,output)
    if not validate_output(output,business['contact'],{'comment':text,'rating':rating}):
        return {'risk':risk,'reply':'','reason':'The local model output failed validation. No reply is usable yet. Try again or evaluate a stronger local model.','status':'blocked'}
    return {'risk':risk,'reply':output['reply'],'reason':output['reason'],'status':'draft'}
