from __future__ import annotations
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PIL import Image, ImageDraw
import meta_history_cache as history
import organic_content_memory as organic
import competitor_research as research
import hermes_gateway as gateway
import meta_insights
import admira_hermes_runtime_patch as runtime
import admira_tool_bridge as bridge
import admira_mcp_server as mcp
import strategic_plan_compiler as compiler
from codex_brand_guides import extract_logo_background_to_transparency


def dashboard_module():
    spec = importlib.util.spec_from_file_location('foundation_test_dashboard', ROOT / 'dashboard/monitoring-dashboard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.d = dashboard_module()
        (ROOT / 'output').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'output')
        self.root = Path(self.temp.name)
        self.brand = {'brand_name': 'Demo', 'colors': '#112233', 'visual_style': 'Minimal', 'tone': 'Cercano', 'logo_usage': 'sin logo', 'references': 'sin referencias', 'asset_notes': 'IA ilustrativa'}
        patches = [
            patch.object(self.d, 'BUSINESS_PROFILE_FILE', self.root / 'business.json'),
            patch.object(self.d, 'TRUSTED_BUYER_TURN_FILE', self.root / 'turn.json'),
            patch.object(self.d, 'TRUSTED_BUYER_TURN_LOCK_FILE', self.root / 'turn.lock'),
            patch.object(self.d, 'CONTENT_ASSET_LIBRARY_FILE', self.root / 'assets.json'),
            patch.object(self.d, 'CONTENT_ASSET_FILES_DIR', self.root / 'assets'),
            patch.object(self.d, 'CONTENT_STRATEGY_FILE', self.root / 'strategy.md'),
            patch.object(self.d, 'active_meta_page_id', return_value='page-1'),
            patch.object(self.d, 'guide_library', side_effect=lambda: {'general_exists': True, 'general': {'fields': self.brand}, 'products': []}),
            patch.object(self.d, 'branding_creatives_status', return_value='completed'),
            patch.object(self.d, 'write_agent_onboarding_plan'),
            patch.object(self.d, 'log_action'),
            patch.object(self.d, 'load_config', return_value=SimpleNamespace(telegram_chat_id='123')),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temp.cleanup)

    def review_ready(self):
        d = self.d
        strategic = d.apply_strategic_profile_updates(d.new_strategic_profile('page-1'),
            {topic: {'status': 'confirmed', 'value': topic, 'confirmation_state': 'buyer_confirmed'} for topic in d.STRATEGIC_PROFILE_TOPICS},
            page_id='page-1', trusted_buyer_confirmation=True,
            evidence={'chat_id': '123', 'session_id': 'session', 'transport': 'telegram', 'message_sequence': 10})
        d.write_json(d.BUSINESS_PROFILE_FILE, d.embed_strategic_profile({}, strategic))
        d.record_trusted_buyer_turn('123', 'session', 10, 'Esos son mis datos', transport='telegram')
        return strategic

    def test_branding_change_requires_new_review_and_natural_confirmation(self):
        d = self.d
        strategic = self.review_ready()
        text = d.ensure_canonical_strategic_review_visible('Perfecto, ya está la información.')
        self.assertIn('#112233', text)
        self.assertTrue(d.record_strategic_review_presented('session', text, '123')['recorded'])
        self.brand['colors'] = '#abcdef'
        d.record_trusted_buyer_turn('123', 'session', 11, 'confirmo todo', transport='telegram')
        with patch.object(d, '_lifecycle_confirmation', return_value=(True, 'semantic_accept')) as semantic:
            result = d.resolve_pending_business_lifecycle_transition(target='business_profile')
            self.assertFalse(result['transitioned'])
            semantic.assert_not_called()
        current = d.strategic_profile_for_page(d.read_json(d.BUSINESS_PROFILE_FILE, {}), page_id='page-1', activate=False)
        new_text = d.business_profile_review_summary(current)
        self.assertIn('#abcdef', new_text)
        self.assertTrue(d.record_strategic_review_presented('session', new_text, '123')['recorded'])
        d.record_trusted_buyer_turn('123', 'session', 12, 'sí, así refleja bien mi negocio', transport='telegram')
        with patch.object(d, '_lifecycle_confirmation', return_value=(True, 'semantic_accept')):
            self.assertTrue(d.resolve_pending_business_lifecycle_transition(target='business_profile')['transitioned'])

    def test_incomplete_branding_never_records_final_review(self):
        strategic = self.review_ready()
        with patch.object(self.d, 'branding_creatives_status', return_value='pending'):
            self.assertEqual(self.d.ensure_canonical_strategic_review_visible('sigamos'), 'sigamos')
            self.assertEqual(self.d.record_strategic_review_presented('session', self.d.business_profile_review_summary(strategic), '123')['reason'], 'branding_not_ready')

    def test_brand_change_during_semantic_call_fails_compare_and_swap(self):
        d = self.d
        strategic = self.review_ready()
        d.record_strategic_review_presented('session', d.business_profile_review_summary(strategic), '123')
        d.record_trusted_buyer_turn('123', 'session', 11, 'confirmo', transport='telegram')
        def classify(*args):
            self.brand['tone'] = 'Elegante'
            return True, 'accepted'
        with patch.object(d, '_lifecycle_confirmation', side_effect=classify):
            result = d.resolve_pending_business_lifecycle_transition(target='business_profile')
        self.assertFalse(result['transitioned'])
        self.assertEqual(result['reason'], 'lifecycle_compare_and_swap_failed')

    def image(self, name, color):
        source = self.root / name
        Image.new('RGB', (32, 32), color).save(source)
        return source

    def test_candidate_lifecycle_and_structure_reference_keep_brand_authority(self):
        d = self.d
        original = self.image('reference.png', 'blue')
        brand = self.image('brand.png', 'green')
        candidate = self.image('candidate.png', 'red')
        source_url = 'https://www.facebook.com/ads/library/?id=1234567890'
        ref = d.save_content_asset_memory({'file_path': str(original), 'category': 'style_reference', 'preservation_mode': 'style_only', 'reference_scope': 'task', 'reference_role': 'competitor_structure', 'source_reference_url': source_url, 'approved_for_ads': False})
        br = d.save_content_asset_memory({'file_path': str(brand), 'category': 'style_reference', 'preservation_mode': 'style_only', 'reference_scope': 'brand'})
        index = {item['id']: item for item in d.load_content_asset_library()['items']}
        paths, evidence = d._creative_style_references({'style_reference': {'mode': 'explicit', 'asset_id': ref['asset_id']}}, index)
        self.assertEqual(len(paths), 2)
        self.assertEqual(evidence['brand_asset_ids'], [br['asset_id']])
        self.assertEqual(evidence['structure_only_asset_ids'], [ref['asset_id']])
        self.assertFalse(index[ref['asset_id']]['approved_for_ads'])
        saved = d.save_content_asset_memory({'file_path': str(candidate), 'category': 'competitor_inspired_creative', 'source_reference_url': source_url, 'vault_name': 'ideas paid', 'inspiration_angle': 'explicar proceso', 'approved_for_ads': False})
        self.assertEqual(saved['asset']['creative_candidate_status'], 'proposed')
        self.assertFalse(saved['asset']['approved_for_daily_content'])
        promoted = d.save_content_asset_memory({'file_path': saved['asset']['file_paths'][0], 'category': 'competitor_inspired_creative', 'approved_for_ads': True})
        self.assertEqual(saved['asset_id'], promoted['asset_id'])
        result = d.search_content_asset_memory({'category': 'competitor_inspired_creative', 'approved_for_ads': True})
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['matches'][0]['source_reference_url'], source_url)
        self.assertEqual(result['matches'][0]['creative_candidate_status'], 'saved_for_paid')
        self.assertFalse(result['matches'][0]['approved_for_daily_content'])
        d.save_content_asset_memory({'file_path': str(candidate), 'category': 'competitor_inspired_creative', 'creative_candidate_status': 'rejected'})
        self.assertEqual(d.search_content_asset_memory({'category': 'competitor_inspired_creative', 'approved_for_ads': True})['count'], 0)
        revised = d.save_content_asset_memory({'file_path': str(candidate), 'category': 'competitor_inspired_creative', 'notes': 'No usar esta propuesta.'})
        self.assertEqual(revised['asset']['creative_candidate_status'], 'rejected')

    def test_before_after_vault_retains_distinct_files_and_roles(self):
        for role, color in [('before', 'blue'), ('after', 'green')]:
            self.d.save_content_asset_memory({'file_path': str(self.image(role + '.png', color)),
                'category': 'customer_testimonial', 'vault_name': 'Casos reales',
                'content_group': 'caso-123', 'visual_role': role, 'approved_for_daily_content': True})
        results = self.d.search_content_asset_memory({'vault_name': 'Casos reales', 'approved_for_daily_content': True})
        self.assertEqual(results['count'], 2)
        self.assertEqual({item['visual_role'] for item in results['matches']}, {'before', 'after'})
        self.assertEqual({item['content_group'] for item in results['matches']}, {'caso-123'})
        self.assertEqual(len({item['file_paths'][0] for item in results['matches']}), 2)

    def test_unified_plan_renders_every_section_and_preserves_legacy(self):
        content = {field: field for field in compiler.PLAN_FIELDS}
        content['organic_content_strategy'] = 'Pilares adecuados al nicho. ' * 20
        text = self.d.render_business_strategic_plan({'schema_version': 2, 'status': 'proposed', 'draft': content})
        self.assertIn(content['organic_content_strategy'].strip(), text)
        self.assertIn('baúl', text)
        self.assertIn('Ads Library', text)
        legacy = {field: field for field in compiler.PLAN_FIELDS if not field.startswith('organic_')}
        self.assertTrue(self.d._master_plan_record_is_complete({'status': 'confirmed', 'content': legacy}))


class CacheAndMemoryTests(unittest.TestCase):
    def test_reused_piece_is_new_novelty_evidence_on_a_later_day(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'organic.json'
            payload = {'caption': 'Consejo reciclado', 'image_path': '/example.png', 'page_id': 'p1'}
            with patch.object(organic, 'now_iso', return_value='2026-09-01T10:00:00+00:00'):
                original = organic.save_post(path, payload)
            with patch.object(organic, 'now_iso', return_value='2026-09-14T10:00:00+00:00'):
                reused = organic.save_post(path, payload)
                staged = organic.save_post(path, {**payload, 'draft_id': reused['draft_id']}, status='pending_approval')
            self.assertNotEqual(original['draft_id'], reused['draft_id'])
            self.assertEqual(staged['draft_id'], reused['draft_id'])
            recent = organic.recent_posts(json.loads(path.read_text()), now=datetime(2026, 9, 20, tzinfo=timezone.utc))
            self.assertEqual([item['draft_id'] for item in recent['items']], [reused['draft_id']])

    def test_annual_ttl_failure_account_scope_and_compact_projection(self):
        with tempfile.TemporaryDirectory() as root:
            now = datetime(2026, 9, 9, tzinfo=timezone.utc)
            calls = []
            def fetch(account, **dates):
                calls.append(dates)
                return {'ok': True, 'metrics': {'account_id': account, 'campaigns': [{'id': str(i), 'spend': i, 'clicks': 2, 'impressions': 100} for i in range(20)]}}
            first = history.history_context(root, 'act_1', 'p1', refresh=True, fetch=fetch, now=now)
            self.assertEqual(first['status'], 'fresh')
            self.assertEqual(len(first['digest']['top_campaigns']), 8)
            self.assertIsNone(first['digest']['kpis']['reach'])
            self.assertEqual(calls[0], {'since': '2025-09-09', 'until': '2026-09-08'})
            cached = history.history_context(root, 'act_1', 'p1', refresh=True, fetch=fetch, now=now + timedelta(hours=1))
            self.assertEqual(len(calls), 1)
            stale = history.history_context(root, 'act_1', 'p1', refresh=True, fetch=lambda *a, **k: {'ok': False}, now=now + timedelta(hours=7))
            self.assertEqual(stale['status'], 'stale')
            self.assertEqual(stale['as_of'], first['as_of'])
            self.assertEqual(stale['digest'], cached['digest'])
            other = history.history_context(root, 'act_2', 'p1', now=now)
            self.assertEqual(other['digest'], {})
            compact = bridge.compact_meta_context({'meta_history': first, 'campaigns': [{'id': 'live'}]})
            self.assertEqual(compact['campaigns'][0]['id'], 'live')
            self.assertEqual(compact['meta_history']['status'], 'fresh')

    def test_proposals_record_before_publication_and_keep_semantic_history(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'organic.json'
            draft = {'caption': 'Una idea', 'image_path': '/example.png', 'page_id': 'p1', 'pillar': 'education', 'topic': 'limpieza', 'hook': 'paso a paso', 'visual_concept': 'comparacion', 'content_group': 'case-1'}
            first = organic.save_post(path, draft)
            self.assertEqual(first['status'], 'proposed')
            organic.save_post(path, {**draft, 'draft_id': first['draft_id'], 'approval_id': 'approval-1'}, status='pending_approval')
            published = organic.save_post(path, {'caption': 'Una idea', 'draft_id': first['draft_id'], 'page_id': 'p1'}, status='published', result={'ok': True, 'post_id': 'meta-id'})
            self.assertEqual(published['hook'], 'paso a paso')
            self.assertEqual(published['image_path'], '/example.png')
            ledger = json.loads(path.read_text())
            self.assertEqual(len(ledger['items']), 1)
            self.assertEqual(len(organic.recent_posts(ledger, page_id='p1')['items']), 1)
            self.assertEqual(organic.recent_posts(ledger, page_id='p2')['items'], [])
            self.assertEqual(organic.recent_posts(ledger, now=datetime.now(timezone.utc) + timedelta(days=16))['items'], [])

    def test_logo_exterior_preserves_enclosed_white_and_original(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'logo.png'
            im = Image.new('RGB', (64, 64), 'white')
            draw = ImageDraw.Draw(im); draw.rectangle((15, 15, 49, 49), fill='black'); draw.rectangle((25, 25, 38, 38), fill='white')
            im.save(source)
            before = source.read_bytes()
            result = extract_logo_background_to_transparency(source)
            self.assertTrue(result['background_removed'])
            out = Image.open(result['path'])
            self.assertEqual(out.getpixel((0, 0))[3], 0)
            self.assertEqual(out.getpixel((30, 30)), (255, 255, 255, 255))
            self.assertEqual(source.read_bytes(), before)

    def test_capture_exact_public_ad_screenshot_and_fail_closed(self):
        url = 'https://www.facebook.com/ads/library/?id=1234567890'
        def fake_run(argv, **kwargs):
            action = argv[4]
            data = {}
            if action == 'get': data = {'url': url}
            elif action == 'snapshot': data = {'snapshot': 'Ad library 1234567890 image campaign'}
            elif action == 'eval': data = {'result': json.dumps({'selector': 'html > body > img', 'media_type': 'img'})}
            elif action == 'screenshot':
                self.assertEqual(argv[5], 'html > body > img')
                Image.new('RGB', (20, 20), 'red').save(argv[6])
            return SimpleNamespace(returncode=0, stdout=json.dumps({'success': True, 'data': data}))
        with tempfile.TemporaryDirectory() as root:
            result = research.capture_public_ad_reference({'url': url}, output_dir=root, run=fake_run)
            self.assertTrue(result['ok'])
            self.assertTrue(result['visual_review_required'])
            self.assertTrue(Path(result['file_path']).exists())
        with self.assertRaises(ValueError): research.canonical_ad_library_url('https://localhost/ads/library/?id=1')
        with self.assertRaises(ValueError): research.canonical_ad_library_url('https://www.facebook.com/ads/library/?q=foo')

    def test_closed_annual_dates_use_account_timezone_and_partial_never_replaces_cache(self):
        with tempfile.TemporaryDirectory() as root:
            now = datetime(2026, 9, 9, 1, tzinfo=timezone.utc)
            calls = []
            def fetch(account, **dates):
                calls.append(dates)
                return {'ok': True, 'metrics': {'account_id': account, 'campaigns': [{'id': 'old', 'spend': 50}]}}
            good = history.history_context(root, 'act_1', 'p1', refresh=True, fetch=fetch, now=now, account_timezone='America/Bogota')
            self.assertEqual(calls, [{'since': '2025-09-08', 'until': '2026-09-07'}])
            partial = history.history_context(root, 'act_1', 'p1', refresh=True, now=now + timedelta(hours=7),
                fetch=lambda *a, **kw: {'ok': True, 'partial': True, 'metrics': {'account_id': 'act_1', 'campaigns': []}})
            self.assertEqual(partial['status'], 'stale')
            self.assertEqual(partial['digest'], good['digest'])

    def test_pagination_cap_is_marked_partial(self):
        with patch.object(meta_insights, 'graph_get', return_value={'ok': True, 'data': {'data': [{'id': '1'}], 'paging': {'next': 'https://graph.facebook.com/v24.0/act_1/insights?after=x'}}}):
            result = meta_insights.graph_rows('/act_1/insights', {}, 'test-token', max_pages=1)
        self.assertTrue(result['partial'])

    def test_daily_content_cron_updates_prompt_without_changing_schedule(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = SimpleNamespace(daily_social_content_enabled=True, daily_social_content_time='10:00', daily_brief_timezone='America/Bogota', hermes_cli='hermes')
            job = {'id': 'job-1', 'schedule': '0 10 * * *', 'deliver': 'telegram:123'}
            with patch.object(gateway, 'telegram_settings', return_value={'enabled': True, 'bot_configured': True, 'chat_id': '123'}), \
                 patch.object(gateway.shutil, 'which', return_value='/bin/hermes'), \
                 patch.object(gateway, 'write_gateway_files', return_value={'workspace': str(root), 'hermes_home': str(root)}), \
                 patch.object(gateway, 'hermes_environment', return_value={}), \
                 patch.object(gateway, '_cron_job', return_value=job), \
                 patch.object(gateway, '_cron_timezone_changed', return_value=False), \
                 patch.object(gateway, '_remember_cron_timezone'), \
                 patch.object(gateway, 'CRON_PROMPT_STATE_FILE', root / 'hashes.json'), \
                 patch.object(gateway, 'DAILY_SOCIAL_CONTENT_PROMPT_FILE', root / 'prompt.md'), \
                 patch.object(gateway.subprocess, 'run', return_value=SimpleNamespace(stdout='jobs', stderr='', returncode=0)) as run:
                first = gateway.ensure_daily_social_content_cron(config)
                self.assertTrue(first['updated'])
                self.assertEqual(sum(call.args[0][1:3] == ['cron', 'edit'] for call in run.call_args_list), 1)
                run.reset_mock()
                second = gateway.ensure_daily_social_content_cron(config)
                self.assertTrue(second['exists'])
                self.assertFalse(any(call.args[0][1:3] == ['cron', 'edit'] for call in run.call_args_list))

    def test_annual_digest_survives_both_runtime_projection_layers(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'src').mkdir()
            (root / 'src' / 'admira_tool_bridge.py').touch()
            annual = {'status': 'stale', 'as_of': '2026-09-08', 'digest': {'kpis': {'spend': 456}}}
            response = {'ok': True, 'live_sync': {'ok': True}, 'context': {'meta_history': annual, 'campaigns': [{'id': '1', 'status': 'ACTIVE'}]}}
            with patch.dict(runtime.os.environ, {'ADMIRA_PRODUCT_ROOT': str(root)}), \
                 patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(response), returncode=0)):
                fetched = runtime._fetch_live_meta_context_for_turn()
            self.assertEqual(fetched['meta_history'], annual)
            compact = runtime._compact_live_meta_context(fetched)
            self.assertEqual(compact['meta_history'], annual)
            self.assertIn('cached annual digest', runtime._append_live_meta_context('Hola', fetched))
            self.assertEqual(compact['current_campaigns'][0]['id'], '1')

    def test_approved_organic_direction_is_scheduled_once_without_overriding_decline(self):
        state = {'complete': True, 'master_plan_status': 'confirmed', 'master_plan': {'organic_daily_plan': 'Dos imágenes cada día.'}}
        text = runtime._admira_compiled_procedure_instruction(state)
        self.assertIn('use save_daily_social_content_settings', text)
        text = runtime._admira_compiled_procedure_instruction({**state, 'daily_social_content_decision': 'declined'})
        self.assertNotIn('use save_daily_social_content_settings', text)

    def test_tool_registry_contract(self):
        names = {name for name, _ in mcp.TOOL_DEFINITIONS}
        for name in ('search_content_assets', 'get_meta_history_context', 'record_organic_content_proposal', 'capture_ad_library_reference'):
            self.assertIn(name, names)
            self.assertEqual(bridge.TOOL_MAP['admira_' + name], name)
            self.assertTrue(mcp.TOOL_INPUT_SCHEMAS[name]['properties'])


if __name__ == '__main__': unittest.main()
