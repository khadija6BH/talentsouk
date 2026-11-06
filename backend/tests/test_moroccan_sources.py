import json
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from backend.job_sources import JobSourceError,fetch_offers
from backend.moroccan_sources import parse_jobposting,PublicMarkup,job_nodes,fetch_marrakech,PublicClient,SameOriginRedirect,MAX_DETAILS


class MoroccanSourcesTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.url='https://www.postule.ma/job/example-123'
        self.node={'@type':'JobPosting','title':'Analyste <b>SQL</b>',
                   'datePosted':self.now.isoformat(),'url':self.url,
                   'hiringOrganization':{'name':'Employer'},
                   'jobLocation':{'address':{'addressLocality':'Marrakech','addressCountry':'MA'}},
                   'employmentType':['FULL_TIME']}

    def test_imports_facts_and_attribution_without_copying_full_announcement(self):
        self.node['description']='private application instructions and long publisher prose'
        row=parse_jobposting(self.node,'Postule.ma',self.url,self.now)
        self.assertEqual(row['title'],'Analyste SQL')
        self.assertEqual(row['company_name'],'Employer')
        self.assertEqual(row['location'],'Marrakech, Maroc')
        self.assertEqual(row['url'],self.url)
        self.assertNotIn('private application',row['description'])

    def test_rejects_foreign_region_only_missing_or_multiple_cities(self):
        for location in ('Casablanca','Marrakech-Safi','Marrakech / Casablanca',''):
            node={**self.node,'jobLocation':{'address':{'addressLocality':location,'addressCountry':'MA'}}}
            self.assertIsNone(parse_jobposting(node,'Postule.ma',self.url,self.now))
        foreign={**self.node,'jobLocation':{'address':{'addressLocality':'Marrakech','addressCountry':'FR'}}}
        self.assertIsNone(parse_jobposting(foreign,'Postule.ma',self.url,self.now))
        multiple={**self.node,'jobLocation':[self.node['jobLocation'],{'address':{'addressLocality':'Rabat','addressCountry':'MA'}}]}
        self.assertIsNone(parse_jobposting(multiple,'Postule.ma',self.url,self.now))

    def test_rejects_old_relative_future_or_expired_dates(self):
        for date in ('il y a 7 jours','', (self.now-timedelta(days=31)).isoformat(),(self.now+timedelta(days=3)).isoformat()):
            self.assertIsNone(parse_jobposting({**self.node,'datePosted':date},'Postule.ma',self.url,self.now))
        self.assertIsNone(parse_jobposting({**self.node,'validThrough':(self.now-timedelta(days=1)).isoformat()},'Postule.ma',self.url,self.now))

    def test_requires_employer_and_matching_canonical_detail_page(self):
        for org in ({},{'name':'recruiter@example.org'},{'name':'Confidentiel'}):
            self.assertIsNone(parse_jobposting({**self.node,'hiringOrganization':org},'Postule.ma',self.url,self.now))
        self.assertIsNone(parse_jobposting({**self.node,'url':'https://evil.invalid/job'},'Postule.ma',self.url,self.now))

    def test_reads_graphs_and_ignores_invalid_json_and_irrelevant_schema(self):
        markup=PublicMarkup()
        markup.feed('<script type="application/ld+json">broken</script><script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'BreadcrumbList'},self.node]})+'</script>')
        self.assertEqual(list(job_nodes(markup.structured)),[self.node])
        self.assertEqual(list(job_nodes({'@type':None})),[])

    def test_honors_robots_and_blocks_external_redirects(self):
        with patch.object(PublicClient,'_read',return_value='User-agent: *\nDisallow: /job/') as read:
            client=PublicClient('https://www.postule.ma/offres-emploi/marrakech')
            with self.assertRaises(JobSourceError):client.get(self.url)
            self.assertEqual(read.call_count,1)
        redirect=SameOriginRedirect('www.postule.ma')
        for target in ('http://127.0.0.1/','https://evil.invalid/','https://user:pass@www.postule.ma/job'):
            with self.assertRaises(JobSourceError):redirect.redirect_request(None,None,302,'',{},target)

    def test_collection_stays_bounded_and_deduplicates_listing_links(self):
        source=self
        class Rules:
            def can_fetch(self,*args):return True
        class FakeClient:
            calls=[]
            def __init__(self,*args):self.rules=Rules();self.deadline=time.monotonic()+100
            def get(self,url):
                self.calls.append(url)
                if '/offres-emploi/' in url:
                    return ''.join('<a href="/job/example-'+str(i)+'">Job</a>' for i in range(MAX_DETAILS+10))+'<a href="/job/example-1">duplicate</a><a href="https://evil.invalid/job/">external</a>'
                node={**source.node,'url':url}
                return '<script type="application/ld+json">'+json.dumps(node)+'</script>'
        with patch('backend.moroccan_sources.PublicClient',FakeClient):
            rows,skipped=fetch_marrakech('postule',location='Marrakech')
        self.assertEqual(len(rows),MAX_DETAILS)
        self.assertEqual(len(FakeClient.calls),MAX_DETAILS+1)
        self.assertEqual(skipped,0)
        self.assertEqual(len({r['url'] for r in rows}),MAX_DETAILS)

    def test_dispatch_uses_no_key_and_rejects_other_countries_before_collection(self):
        with patch('backend.moroccan_sources.fetch_marrakech',return_value=([],0)) as collect:
            self.assertEqual(fetch_offers('jobradar','ma',location='Marrakech'),([],0))
            collect.assert_called_once_with('jobradar','','Marrakech')
            with self.assertRaises(JobSourceError):fetch_offers('jobradar','fr')
        with self.assertRaises(JobSourceError):fetch_marrakech('postule',location='Casablanca')

    def test_changed_detail_format_is_an_error_instead_of_a_false_empty_feed(self):
        class Rules:
            def can_fetch(self,*args):return True
        class FakeClient:
            def __init__(self,*args):self.rules=Rules();self.deadline=time.monotonic()+100
            def get(self,url):
                return '<a href="/job/one">One</a>' if '/offres-emploi/' in url else '<h1>Changed page</h1>'
        with patch('backend.moroccan_sources.PublicClient',FakeClient):
            with self.assertRaises(JobSourceError):fetch_marrakech('postule',location='Marrakech')
