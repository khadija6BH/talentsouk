import os
import unittest
from unittest.mock import patch
from backend.job_sources import fetch_offers,fetch_offer_pages,JobSourceError,_json
from urllib.error import HTTPError

class JobSourcesTest(unittest.TestCase):
    def test_pages_collect_distinct_urls_and_stop_repeated_or_empty_pages(self):
        first={'title':'Engineer','url':'https://ma.jooble.org/jdp/1'}
        second={'title':'Analyst','url':'https://ma.jooble.org/jdp/2'}
        with patch('backend.job_sources.fetch_offers',side_effect=[([first],0),([{**first,'url':first['url']+'?utm_source=email'},second],1),([],0)]) as fetch:
            rows,skipped=fetch_offer_pages('jooble','ma',location='Marrakech',pages=5)
            self.assertEqual(rows,[first,second]);self.assertEqual(skipped,2)
            self.assertEqual([call.kwargs['page'] for call in fetch.call_args_list],[1,2,3])
        with patch('backend.job_sources.fetch_offers',return_value=([first],0)) as fetch:
            rows,_=fetch_offer_pages('jooble','ma',pages=5)
            self.assertEqual(rows,[first]);self.assertEqual(fetch.call_count,2)

    def test_page_limit_and_later_failure_never_start_database_import(self):
        for pages in (0,6,True):
            with self.assertRaises(JobSourceError):fetch_offer_pages('jooble','ma',pages=pages)
        with self.assertRaises(JobSourceError):fetch_offer_pages('jobicy','remote',pages=2)
        from backend.opportunity_radar import refresh_external_offers
        with patch('backend.job_sources.fetch_offers',side_effect=[([{'url':'https://ma.jooble.org/jdp/1'}],0),JobSourceError('Unavailable')]),patch('backend.opportunity_radar.import_external_offers') as save:
            with self.assertRaises(JobSourceError):refresh_external_offers('jooble','ma',pages=5)
            save.assert_not_called()

    def test_adzuna_uses_requested_page(self):
        with patch.dict(os.environ,{'ADZUNA_APP_ID':'test-id','ADZUNA_APP_KEY':'test-key'}),patch('backend.job_sources._json',return_value={'results':[]}) as fetch:
            fetch_offers('adzuna','fr',page=3)
            self.assertIn('/search/3?',fetch.call_args.args[0])

    def test_credentials_and_country_are_required(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(JobSourceError):fetch_offers('jooble','ma')
            with self.assertRaises(JobSourceError):fetch_offers('adzuna','fr')
        with self.assertRaises(JobSourceError):fetch_offers('jooble','fr')
        with self.assertRaises(JobSourceError):fetch_offers('adzuna','ma')
        with self.assertRaises(JobSourceError):fetch_offers('arbeitnow','ma')
    def test_adzuna_mapping(self):
        data={'results':[{'title':'Analyst','company':{'display_name':'Example'},'location':{'display_name':'Paris'},'redirect_url':'https://example.invalid/job','description':'<p>SQL</p>','created':'2026-10-11','contract_type':'permanent'}]}
        with patch.dict(os.environ,{'ADZUNA_APP_ID':'test-id','ADZUNA_APP_KEY':'test-key'}),patch('backend.job_sources._json',return_value=data) as call:
            rows,skipped=fetch_offers('adzuna','fr','analyst','Paris')
            self.assertEqual(rows[0]['source'],'Adzuna');self.assertEqual(rows[0]['company_name'],'Example')
            self.assertNotIn('<p>',rows[0]['description']);self.assertEqual(skipped,0)
            self.assertIn('/jobs/fr/search/1',call.call_args[0][0])
    def test_jooble_mapping_uses_morocco(self):
        data={'jobs':[{'title':'Developer','company':'Example','location':'Marrakech','link':'https://example.invalid/job','snippet':'Python','type':'Full-time','updated':'2026-10-11'}]}
        with patch.dict(os.environ,{'JOOBLE_API_KEY':'test-key'}),patch('backend.job_sources._json',return_value=data) as call:
            rows,_=fetch_offers('jooble','ma','Python','Marrakech')
            self.assertEqual(rows[0]['source'],'Jooble');self.assertTrue(call.call_args[0][0].startswith('https://ma.jooble.org/api/'))
            self.assertEqual(call.call_args[0][1]['location'],'Marrakech')
            self.assertEqual(call.call_args[0][1]['ResultOnPage'],100)
    def test_arbeitnow_filters_and_rejects_bad_links(self):
        data={'data':[{'title':'Python Developer','company_name':'Example','location':'Berlin','url':'https://example.invalid/job','description':'<p>Python</p>','created_at':1700000000}, {'title':'Python Developer','company_name':'Example','location':'Berlin','url':'javascript:alert(1)'}]}
        with patch('backend.job_sources._json',return_value=data):
            rows,skipped=fetch_offers('arbeitnow','de','Python','Berlin');self.assertEqual(len(rows),1);self.assertEqual(skipped,1)
            self.assertEqual(fetch_offers('arbeitnow','de','Unknown','Berlin')[0],[])
    def test_api_error_does_not_disclose_key(self):
        secret='never-show-this-key'
        with patch('backend.job_sources.urlopen',side_effect=HTTPError('https://example.invalid/'+secret,401,secret,None,None)):
            with self.assertRaises(JobSourceError) as caught:_json('https://example.invalid/'+secret)
            self.assertNotIn(secret,str(caught.exception))

    def test_jobicy_mapping_preserves_eligibility_and_source(self):
        data={'jobs':[{'jobTitle':'Data Analyst','companyName':'Example','jobGeo':'USA','url':'https://jobicy.com/jobs/example','jobDescription':'<p>SQL</p>','jobType':['Full-Time'],'pubDate':'2026-10-11'}]}
        with patch('backend.job_sources._jobicy_feed',return_value=data):
            rows,_=fetch_offers('jobicy','remote','SQL','USA')
            self.assertEqual(rows[0]['source'],'Jobicy');self.assertEqual(rows[0]['location'],'USA')
            self.assertEqual(rows[0]['offer_type'],'Full-Time')
            self.assertEqual(fetch_offers('jobicy','remote','unknown','')[0],[])
        with self.assertRaises(JobSourceError):fetch_offers('jobicy','ma')
