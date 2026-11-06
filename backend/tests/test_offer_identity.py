import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from backend.opportunity_radar import LocalOfferSync, import_external_offers
from backend.offer_lifecycle import ensure_catalog_schema


class OfferIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'offers.db'
        conn = self.connect()
        conn.executescript('''
            CREATE TABLE companies(id INTEGER PRIMARY KEY,name TEXT,area TEXT,has_offer INTEGER DEFAULT 0);
            INSERT INTO companies VALUES(1,'Employer','Marrakech',0);
            CREATE TABLE offers(id INTEGER PRIMARY KEY,company_id INTEGER,company_name TEXT,
                title TEXT,source TEXT,url TEXT,location TEXT,offer_type TEXT,publication_date TEXT,description TEXT);
            CREATE TABLE offer_sync_metadata(offer_id INTEGER PRIMARY KEY,first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                last_checked TEXT DEFAULT CURRENT_TIMESTAMP,adapter TEXT);
            CREATE TABLE opportunity_refreshes(id INTEGER PRIMARY KEY,checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_count INTEGER,updated_count INTEGER,provider TEXT,country TEXT);
        ''')
        ensure_catalog_schema(conn)
        self.incoming = dict(company_id=1,company_name='Employer',title='Engineer',source='Jooble',
                             url='https://ma.jooble.org/desc/-123?ckey=new',location='Marrakech',offer_type='',
                             publication_date=datetime.now(timezone.utc).isoformat(),description='SQL')
        for identifier,token,status in ((1,'one','pending'),(2,'two','approved')):
            entry = dict(self.incoming,url='https://ma.jooble.org/desc/-123?ckey='+token)
            fields = list(entry)
            conn.execute('INSERT INTO offers(id,'+','.join(fields)+') VALUES('+','.join('?' for _ in range(len(fields)+1))+')',(identifier,*entry.values()))
            conn.execute('INSERT INTO admin_offer_reviews VALUES(?,?,?,CURRENT_TIMESTAMP)',(identifier,status,''))
            conn.execute("INSERT INTO offer_catalog_status VALUES(?,1,CURRENT_TIMESTAMP,'recent_api_response')",(identifier,))
        conn.commit();conn.close()

    def connect(self):
        conn=sqlite3.connect(self.path);conn.row_factory=sqlite3.Row
        return conn

    def tearDown(self):
        self.temp.cleanup()

    def test_tracking_alias_refresh_reuses_approved_id_without_deleting_history(self):
        with patch('backend.opportunity_radar.get_db_connection',side_effect=self.connect),patch('backend.radar_watch.alert_preferences',return_value=[]),patch('backend.radar_watch.notify_new_offers'):
            result=import_external_offers('jooble','ma',[self.incoming])
        self.assertEqual(result['created'],0);self.assertEqual(result['updated'],1)
        conn=self.connect()
        self.assertEqual(conn.execute('SELECT count(*) FROM offers').fetchone()[0],2)
        states={row[0]:row[1] for row in conn.execute('SELECT offer_id,is_active FROM offer_catalog_status')}
        self.assertEqual(states,{1:0,2:1})
        self.assertEqual(conn.execute('SELECT offer_id FROM offer_sync_metadata').fetchone()[0],2)
        self.assertEqual(conn.execute('SELECT status FROM admin_offer_reviews WHERE offer_id=2').fetchone()[0],'approved')
        conn.close()

    def test_rejected_source_identity_cannot_be_bypassed_by_an_approved_alias(self):
        conn=self.connect()
        conn.execute("UPDATE admin_offer_reviews SET status='rejected' WHERE offer_id=1")
        sync=LocalOfferSync(conn)
        self.assertEqual(sync.offer(self.incoming),1)
        self.assertEqual(conn.execute('SELECT status FROM admin_offer_reviews WHERE offer_id=1').fetchone()[0],'rejected')
        conn.close()

    def test_rejected_and_pending_records_stay_hidden_during_published_refresh(self):
        conn=self.connect()
        conn.execute("UPDATE admin_offer_reviews SET status='rejected' WHERE offer_id=1")
        conn.commit();conn.close()
        with patch('backend.opportunity_radar.get_db_connection',side_effect=self.connect),patch('backend.radar_watch.alert_preferences',return_value=[]),patch('backend.radar_watch.notify_new_offers'):
            import_external_offers('jooble','ma',[self.incoming])
        conn=self.connect()
        self.assertEqual(conn.execute('SELECT count(*) FROM offer_catalog_status WHERE is_active=1').fetchone()[0],0)
        self.assertEqual(conn.execute('SELECT count(*) FROM offers').fetchone()[0],2)
        conn.close()
