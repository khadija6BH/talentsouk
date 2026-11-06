import os
import unittest
from unittest.mock import MagicMock, patch
from psycopg.pq import TransactionStatus
from backend import postgres


class ServerlessPoolTest(unittest.TestCase):
    def check_mode(self,vercel,expected_max):
        raw=MagicMock()
        raw.closed=False
        raw.info.transaction_status=TransactionStatus.IDLE
        pool=MagicMock()
        pool.getconn.return_value=raw
        with patch.dict(os.environ,{'VERCEL':vercel}),patch.dict(postgres.POOLS,{},clear=True),patch.object(postgres,'ConnectionPool',return_value=pool) as regular,patch.object(postgres,'NullConnectionPool',return_value=pool) as no_idle,patch.object(postgres.atexit,'register'):
            conn=postgres.Connection('postgresql://test.invalid/unused')
            chosen=no_idle if vercel=='1' else regular
            other=regular if vercel=='1' else no_idle
            chosen.assert_called_once()
            other.assert_not_called()
            self.assertEqual(chosen.call_args.kwargs['max_size'],expected_max)
            self.assertEqual(chosen.call_args.kwargs['min_size'],0)
            self.assertIsNone(chosen.call_args.kwargs['kwargs']['prepare_threshold'])
            conn.close();conn.close()
            pool.putconn.assert_called_once_with(raw)
            raw.rollback.assert_not_called()

    def test_vercel_does_not_keep_idle_session_connections(self):
        self.check_mode('1',2)

    def test_local_pool_behavior_is_preserved(self):
        self.check_mode('0',5)

    def test_unfinished_transaction_is_rolled_back_before_releasing_slot(self):
        raw=MagicMock()
        raw.closed=False
        raw.info.transaction_status=TransactionStatus.INTRANS
        pool=MagicMock()
        events=[]
        raw.rollback.side_effect=lambda: events.append('rollback')
        pool.putconn.side_effect=lambda conn: events.append('release')
        postgres.release(pool,raw)
        self.assertEqual(events,['rollback','release'])
