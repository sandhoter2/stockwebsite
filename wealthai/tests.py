import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from wealthai.llm import choose_provider
from wealthai.models import Holding, Portfolio, ReportTask


class WealthAIAuthTests(TestCase):
    def test_portfolios_require_auth(self):
        r = self.client.get('/api/wealth/portfolios/')
        self.assertIn(r.status_code, (401, 403))


class WealthAIPortfolioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('investor', password='pw12345!')
        self.other = User.objects.create_user('other', password='pw12345!')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_portfolio_returns_uuid(self):
        r = self.client.post('/api/wealth/portfolios/', {
            'name': 'Core equity',
            'description': 'Long-term holdings',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['name'], 'Core equity')
        self.assertTrue(r.data['id'])
        self.assertEqual(Portfolio.objects.filter(owner=self.user).count(), 1)

    def test_list_only_own_portfolios(self):
        Portfolio.objects.create(owner=self.user, name='Mine')
        Portfolio.objects.create(owner=self.other, name='Theirs')
        r = self.client.get('/api/wealth/portfolios/')
        self.assertEqual(r.status_code, 200)
        names = [row['name'] for row in r.data['results']]
        self.assertEqual(names, ['Mine'])

    def test_patch_holdings_upserts_and_values(self):
        p = Portfolio.objects.create(owner=self.user, name='Core')
        r = self.client.patch(f'/api/wealth/portfolios/{p.id}/holdings/', {
            'holdings': [
                {'symbol': 'AAPL', 'shares': 10, 'cost_basis': 150},
                {'symbol': 'MSFT', 'shares': 5, 'cost_basis': 300},
            ],
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['holdings']), 2)
        self.assertEqual(Holding.objects.filter(portfolio=p).count(), 2)
        aapl = Holding.objects.get(portfolio=p, symbol='AAPL')
        self.assertEqual(aapl.shares, 10)
        self.assertEqual(aapl.cost_basis, 150)

    def test_delete_portfolio_removes_holdings_and_tasks(self):
        p = Portfolio.objects.create(owner=self.user, name='Core')
        Holding.objects.create(portfolio=p, symbol='AAPL', shares=1, cost_basis=10)
        ReportTask.objects.create(portfolio=p, owner=self.user, status='queued')
        r = self.client.delete(f'/api/wealth/portfolios/{p.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Portfolio.objects.filter(pk=p.pk).exists())
        self.assertEqual(Holding.objects.count(), 0)
        self.assertEqual(ReportTask.objects.count(), 0)

    def test_cannot_delete_someone_elses_portfolio(self):
        p = Portfolio.objects.create(owner=self.other, name='Secret')
        r = self.client.delete(f'/api/wealth/portfolios/{p.id}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Portfolio.objects.filter(pk=p.pk).exists())


class WealthAIHistoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('investor', password='pw12345!')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.p = Portfolio.objects.create(owner=self.user, name='Core')
        Holding.objects.create(portfolio=self.p, symbol='AAPL', shares=2, cost_basis=100)

    @patch('wealthai.engine.quote_price', return_value=120.0)
    def test_history_returns_timeseries(self, _quote):
        r = self.client.get(f'/api/wealth/portfolios/{self.p.id}/history/?days=7')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data['points']), 2)
        self.assertIn('date', r.data['points'][0])
        self.assertIn('value', r.data['points'][0])
        self.assertEqual(r.data['points'][-1]['value'], 240.0)


class WealthAIReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('investor', password='pw12345!')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.p = Portfolio.objects.create(owner=self.user, name='Core')
        Holding.objects.create(portfolio=self.p, symbol='AAPL', shares=10, cost_basis=150)
        Holding.objects.create(portfolio=self.p, symbol='MSFT', shares=4, cost_basis=300)

    def test_report_without_holdings_is_400(self):
        empty = Portfolio.objects.create(owner=self.user, name='Empty')
        r = self.client.post(f'/api/wealth/portfolios/{empty.id}/report/', {
            'provider': 'groq',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    @patch('wealthai.engine.quote_price', side_effect=lambda symbol, **kw: {'AAPL': 180.0, 'MSFT': 420.0}[symbol])
    @patch('wealthai.llm.complete', return_value=('## Outlook\nHold AAPL.', 'groq', 'mixtral-8x7b-32768'))
    def test_report_runs_and_exposes_live_task_log(self, _llm, _quote):
        r = self.client.post(f'/api/wealth/portfolios/{self.p.id}/report/', {
            'provider': 'groq',
            'format': 'markdown',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        task_id = r.data['id']
        self.assertEqual(r.data['status'], 'queued')

        run = self.client.post(f'/api/wealth/tasks/{task_id}/run/', {}, format='json')
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.data['status'], 'succeeded')
        self.assertIn('Hold AAPL', run.data['markdown'])
        self.assertEqual(run.data['provider'], 'groq')
        steps = [row['step'] for row in run.data['log']]
        self.assertIn('queued', steps)
        self.assertIn('prices', steps)
        self.assertIn('ai', steps)
        self.assertIn('done', steps)

        poll = self.client.get(f'/api/wealth/tasks/{task_id}/')
        self.assertEqual(poll.status_code, 200)
        self.assertEqual(poll.data['status'], 'succeeded')
        self.assertTrue(poll.data['log'])
        self.assertIn('metrics', poll.data)
        self.assertEqual(poll.data['metrics']['holdings'], 2)

    def test_task_list_shows_own_running_and_done(self):
        t1 = ReportTask.objects.create(portfolio=self.p, owner=self.user, status='running')
        t1.append_log('prices', 'Fetching quotes')
        ReportTask.objects.create(portfolio=self.p, owner=self.user, status='succeeded',
                                  markdown='# Done')
        r = self.client.get('/api/wealth/tasks/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['results']), 2)
        statuses = {row['status'] for row in r.data['results']}
        self.assertEqual(statuses, {'running', 'succeeded'})


class ChooseProviderTests(TestCase):
    def test_short_prompt_defaults_to_groq(self):
        self.assertEqual(choose_provider('groq', holdings_count=2), 'groq')

    def test_openai_requested_is_honoured(self):
        self.assertEqual(choose_provider('openai', holdings_count=2), 'openai')

    def test_auto_uses_openai_for_large_books(self):
        self.assertEqual(choose_provider('auto', holdings_count=12), 'openai')
        self.assertEqual(choose_provider('auto', holdings_count=2), 'groq')
