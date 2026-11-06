import sqlite3
import unittest
from datetime import datetime,timezone,timedelta
from backend.offer_lifecycle import recent_offer,ensure_catalog_schema,activate_offer,expire_offers
from backend.radar_watch import relevance_reason,notify_new_offers


class OfferLifecycleTest(unittest.TestCase):
    def test_expiration_preserves_fresh_records_and_batches_large_backlog(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.execute('CREATE TABLE offers(id INTEGER PRIMARY KEY,location TEXT,publication_date TEXT)')
        ensure_catalog_schema(c)
        now=datetime.now(timezone.utc)
        for identifier in range(1,1003):
            c.execute('INSERT INTO offers VALUES(?,?,?)',(identifier,'Marrakech',now.isoformat()))
            verified=(now-timedelta(days=8) if identifier<=1001 else now).strftime('%Y-%m-%d %H:%M:%S')
            c.execute("INSERT INTO offer_catalog_status VALUES(?,1,?,'recent_api_response')",(identifier,verified))
        statements=[]
        c.set_trace_callback(statements.append)
        expire_offers(c)
        self.assertEqual(c.execute('SELECT offer_id FROM offer_catalog_status WHERE is_active=1').fetchone()[0],1002)
        self.assertEqual(c.execute('SELECT count(*) FROM offers').fetchone()[0],1002)
        self.assertEqual(sum(query.startswith('UPDATE offer_catalog_status') for query in statements),3)
        c.close()

    def test_freshness_city_and_unknown_dates(self):
        now=datetime.now(timezone.utc)
        row={'location':'Marrakech','publication_date':(now-timedelta(days=2)).isoformat()}
        self.assertTrue(recent_offer(row,now))
        self.assertTrue(recent_offer({**row,'publication_date':now.strftime('%Y-%m-%dT00:00:00.0000000')},now))
        self.assertFalse(recent_offer({**row,'publication_date':(now-timedelta(days=31)).isoformat()},now))
        self.assertFalse(recent_offer({**row,'location':'Safi, Marrakech-Safi, Maroc'},now))
        self.assertFalse(recent_offer({**row,'publication_date':''},now))

    def test_matching_respects_skills_role_and_location(self):
        offer={'title':'Data Analyst','description':'SQL and Python','location':'Marrakech'}
        profile={'target_position':'Data Analyst','alert_skills':'SQL, Python','target_location':'Marrakech'}
        self.assertIsNotNone(relevance_reason(profile,offer))
        self.assertIsNone(relevance_reason({**profile,'alert_skills':'Nursing'},offer))
        self.assertIsNone(relevance_reason({**profile,'target_location':'Rabat'},offer))
        self.assertIsNone(relevance_reason({'target_position':'Marketing Manager'},offer))

    def test_notification_is_per_user_per_offer_once(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY);
            INSERT INTO users VALUES(1);INSERT INTO users VALUES(2);
            CREATE TABLE notifications(id INTEGER PRIMARY KEY,user_id INTEGER,kind TEXT,title TEXT,message TEXT,url TEXT);''')
        offer={'id':9,'title':'Data Analyst','description':'SQL','source':'Jooble'}
        prefs=[(1,{'target_position':'Data Analyst','alert_skills':'SQL'}),(2,{'target_position':'Marketing Manager'})]
        notify_new_offers(c,[offer],prefs);notify_new_offers(c,[offer],prefs)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)
        self.assertEqual(c.execute('SELECT user_id FROM notifications').fetchone()[0],1)
        c.close()

    def test_archiving_keeps_original_offer(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.execute('CREATE TABLE offers(id INTEGER PRIMARY KEY,location TEXT,publication_date TEXT)')
        c.execute('INSERT INTO offers VALUES(1,?,?)',('Marrakech',(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()))
        ensure_catalog_schema(c);activate_offer(c,1);expire_offers(c)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM offers').fetchone()[0],1)
        self.assertEqual(c.execute('SELECT is_active FROM offer_catalog_status').fetchone()[0],0)
        c.close()
