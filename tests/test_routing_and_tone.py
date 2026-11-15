import unittest
from reviewer.ai import assess,validate_output
from reviewer.demo import generate_demo


class RoutingTests(unittest.TestCase):
    def test_product_safety_always_held_even_with_five_stars(self):
        for text in ['Excellent prices, but the battery started smoking when I got home.',
                     'My phone charger began to smoke.', 'The heater caught fire.',
                     'The kettle overheated and sparked.', 'The device exploded.',
                     'I got an electric shock from the drill.']:
            with self.subTest(text=text): self.assertEqual(assess(text,5),'sensitive')
    def test_smoking_area_is_not_confused_with_product_safety(self):
        self.assertEqual(assess('Friendly staff and a nice smoking area.',5),'routine')
    def test_mixed_feedback_is_not_treated_as_pure_praise(self):
        for text in ['Helpful advice and fair prices. Parking was difficult.',
                     'Lovely people but checkout was very slow.',
                     'Good prices, but the drill stopped working after one use.']:
            with self.subTest(text=text): self.assertEqual(assess(text,5),'complaint')
    def test_no_complaints_phrase_is_not_a_complaint(self):
        for text in ['No complaints—quick checkout and helpful advice',
                     'I have no complaints. Great shop.', 'No complaint at all, excellent service.']:
            with self.subTest(text=text): self.assertEqual(assess(text,5),'routine')
    def test_negated_complaint_does_not_erase_later_problem(self):
        self.assertEqual(assess('No complaints about prices, but the staff were rude.',5),'complaint')
        self.assertEqual(assess('No complaints, except my battery started smoking.',5),'sensitive')
        self.assertEqual(assess('Not without complaints. The staff were rude.',5),'complaint')
    def test_keyword_fragments_in_positive_words_do_not_trigger(self):
        for text in ['Great chocolate and helpful advice.', 'The latest tools are excellent.', 'Our collaboration was great.']:
            with self.subTest(text=text): self.assertEqual(assess(text,5),'routine')
    def test_safety_demo_does_not_call_ai(self):
        class NoAI:
            def generate(self,*args): raise AssertionError('Safety case must be held before AI generation')
        result=generate_demo({'facts_approved':1,'model':'local:test','contact':''},NoAI(),'Great prices, but the battery started smoking.',5)
        self.assertEqual(result['status'],'held'); self.assertEqual(result['risk'],'sensitive')
    def test_generic_contact_placeholder_rejected_when_real_contact_available(self):
        output={'reply':'Please contact the shop through its published support details.','risk':'complaint','reason':'Product issue'}
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'Drill stopped working','rating':2}))
    def test_parking_criticism_cannot_be_omitted(self):
        output={'reply':'Glad you liked the advice and prices. Thanks for your support!','risk':'complaint','reason':'Parking difficulty'}
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'Helpful advice, but parking was difficult.','rating':4}))
    def test_plural_products_cannot_bypass_safety(self):
        for text in ['The chargers started smoking.','The tools overheated.','The devices were burning.']:
            with self.subTest(text=text): self.assertEqual(assess(text,5),'sensitive')
    def test_unaddressed_complaints_are_not_negated_praise(self):
        for text in ['No complaints were addressed by the shop.','No complaints have been resolved.','No complaints are taken seriously.']:
            with self.subTest(text=text): self.assertEqual(assess(text,5),'complaint')
    def test_contact_us_needs_actual_approved_contact(self):
        output={'reply':'Sorry the drill stopped working. Please contact us so we can help.','risk':'complaint','reason':'Product issue'}
        self.assertFalse(validate_output(output,'support@example.com',{'comment':'Drill stopped working','rating':2}))
    def test_parking_acknowledgement_allowed(self):
        output={'reply':'Glad the advice helped! Sorry parking was tricky, and we appreciate you mentioning it.','risk':'complaint','reason':'Mixed praise and parking concern'}
        self.assertTrue(validate_output(output,'support@example.com',{'comment':'Helpful advice, but parking was difficult.','rating':4}))

if __name__=='__main__': unittest.main()
