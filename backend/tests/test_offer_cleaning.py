import unittest
from backend.offer_cleaning import marrakech_location,clean_offers


class OfferCleaningTest(unittest.TestCase):
    def test_jooble_click_parameters_do_not_create_new_offer_identities(self):
        from backend.offer_cleaning import canonical_url
        self.assertEqual(canonical_url('https://ma.jooble.org/desc/-123?ckey=one&pos=1'),canonical_url('https://ma.jooble.org/desc/-123?ckey=two&pos=99'))
        self.assertNotEqual(canonical_url('https://example.org/job?id=1'),canonical_url('https://example.org/job?id=2'))
        self.assertNotEqual(canonical_url('https://ma.jooble.org/desc/-123'),canonical_url('https://ma.jooble.org/desc/-456'))

    def test_city_is_not_the_region(self):
        for city in ['Marrakech','Marrakesh, Marrakech-Safi, Maroc','Morocco, Marrakech-Medina','Royal Mansour Marrakech, Maroc','مراكش']:
            self.assertTrue(marrakech_location(city),city)
        for city in ['Casablanca',', Marrakech-Safi, Maroc','Safi, Marrakech-Safi, Maroc','Essaouira, Marrakech-Safi, Maroc','Ben Guerir, Marrakech-Safi, Maroc','Marrakech / Casablanca']:
            self.assertFalse(marrakech_location(city),city)

    def test_provenance_placeholders_and_duplicate_urls(self):
        base=dict(id=1,title='Engineer',company_name='Employer',location='Marrakech',source='Jooble',adapter='jooble',url='https://ma.jooble.org/jdp/123')
        good,bad=clean_offers([base,{**base,'id':2,'url':base['url']+'?utm_source=email'},
            {**base,'id':3,'adapter':None},{**base,'id':4,'company_name':'Test Company','url':'https://ma.jooble.org/jdp/456'},
            {**base,'id':5,'url':'https://example.com/jobs/12'}])
        self.assertEqual(len(good),1)
        self.assertEqual(good[0]['id'],2)
        self.assertEqual({r['exclusion_reason'] for r in bad},{'duplicate_source_url','api_import_provenance_not_recorded','placeholder_marker','source_url_needs_review'})
