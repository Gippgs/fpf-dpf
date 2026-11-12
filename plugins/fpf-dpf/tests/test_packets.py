import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import corpus
import packets
import harness
from fixtures import published

CORE = '# First Principles Framework\n## A.1 - Systems\nBoundary ownership.\n'
DPF = '# Maintenance DPF\n## ME.1 - Inspection\nInspect corrosion.\n## ME.2 - Repair\nRepair pump.\n## ME.3 - Feedback\nLearn.\n'


class PacketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'data'
        self.files = {'FPF-Spec.md': CORE, 'maintenance.md': DPF}
        self.publish()
        self.old = corpus.current_snapshot(self.data)[0].name

    def publish(self, files=None):
        return corpus.publish(self.data, published(files or self.files), 'a' * 40, 'test')

    def test_all_reads_keep_old_snapshot_after_update(self):
        self.publish({'FPF-Spec.md': CORE, 'new.md': DPF.replace('corrosion', 'erosion')})
        self.assertIn('corrosion', corpus.read(self.data, 'ME.1', snapshot=self.old)['text'])
        self.assertEqual(corpus.catalog(self.data, snapshot=self.old)['snapshot'], self.old)
        self.assertEqual(corpus.routes(self.data, snapshot=self.old)['snapshot'], self.old)
        self.assertTrue(corpus.search(self.data, 'corrosion', snapshot=self.old)['results'])
        self.assertFalse(corpus.status(self.data, self.old)['is_active'])

    def test_invalid_or_missing_snapshot_never_falls_back(self):
        for invalid in ('../current', 'z' * 32, 'f' * 32):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                corpus.read(self.data, 'A.1', snapshot=invalid)

    def test_packet_hit_skips_search_and_read(self):
        first = packets.packet(self.data, 'corrosion')
        with patch.object(corpus, 'search', side_effect=AssertionError('searched again')):
            second = packets.packet(self.data, 'corrosion')
        self.assertFalse(first['cache_hit'])
        self.assertTrue(second['cache_hit'])
        self.assertEqual(first['sources'], second['sources'])

    def test_cache_is_invalidated_by_new_unselected_document_same_commit(self):
        first = packets.packet(self.data, 'corrosion')
        self.publish(self.files | {'new.md': '# New DPF\n## NEW.1 - Domain\ncorrosion feedback.\n'})
        second = packets.packet(self.data, 'corrosion')
        self.assertNotEqual(first['packet_id'], second['packet_id'])
        self.assertFalse(second['cache_hit'])

    def test_source_limit_reports_unretrieved_matches(self):
        text = '# Maintenance DPF\n' + '\n'.join(f'## ME.{i} - Case\nInspect corrosion.' for i in range(1, 6))
        self.publish({'FPF-Spec.md': CORE, 'maintenance.md': text})
        p = packets.packet(self.data, 'corrosion', limit=3)
        self.assertEqual(p['candidate_count'], 5)
        self.assertEqual(p['omitted_count'], 2)
        self.assertEqual(len(p['sources']), 3)

    def test_rename_and_removal_never_reuse_current_packet(self):
        first = packets.packet(self.data, 'maintenance.md', selectors=['ME.1'])
        self.publish({'FPF-Spec.md': CORE, 'renamed.md': DPF})
        new = packets.packet(self.data, 'maintenance.md', selectors=['ME.1'])
        self.assertNotEqual(first['packet_id'], new['packet_id'])
        self.assertEqual(new['sources'][0]['path'], 'renamed.md')
        self.publish({'FPF-Spec.md': CORE})
        self.assertEqual(packets.packet(self.data, 'corrosion')['sources'], [])
        self.assertEqual(packets.packet(self.data, 'corrosion', snapshot=self.old)['sources'][0]['path'], 'maintenance.md')

    def test_changed_scope_and_budget_get_distinct_cache(self):
        a = packets.packet(self.data, 'corrosion', scope='draft')
        b = packets.packet(self.data, 'corrosion', scope='release')
        c = packets.packet(self.data, 'corrosion', scope='draft', max_chars=3000)
        self.assertEqual(len({p['packet_id'] for p in (a, b, c)}), 3)

    def test_exact_lines_citations_and_partial_coverage_with_hard_char_bound(self):
        long = '# Maintenance DPF\n## ME.1 - Inspection\n' + '\n'.join('corrosion ' + str(i) + ' \u0430\u0431\u0432\u0433\u0434' * 20 for i in range(120))
        self.publish({'FPF-Spec.md': CORE, 'maintenance.md': long})
        p = packets.packet(self.data, 'inspection', selectors=['ME.1'], max_chars=2500)
        self.assertLessEqual(len(packets.serialized(p)), 2500)
        s = p['sources'][0]
        expected = corpus.read(self.data, s['selector'], start=s['start'], lines=s['end'] - s['start'] + 1)
        self.assertEqual(s['text'], expected['text'])
        self.assertEqual(s['url'], expected['url'])
        self.assertTrue(s['partial'])
        self.assertIsNotNone(s['next_line'])
        self.assertEqual(len(s['document_hash']), 64)

    def test_long_indivisible_line_reports_omission_not_false_complete(self):
        self.publish({'FPF-Spec.md': CORE, 'maintenance.md': '# Maintenance DPF\n## ME.1 - Inspection\n' + 'x' * 10000})
        p = packets.packet(self.data, 'ME.1', max_chars=2000)
        self.assertTrue(p['sources'][0]['partial'])
        self.assertEqual(p['sources'][0]['next_line'], 3)

    def test_ambiguous_exact_id_is_not_silently_limited_to_one(self):
        self.publish(self.files | {'other.md': '# Other DPF\n## ME.1 - Another\nDifferent scope.\n'})
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            packets.packet(self.data, 'ME.1', limit=1)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            packets.packet(self.data, 'inspection', selectors=['ME.1'])

    def test_search_packet_resolves_second_duplicate_pattern_in_same_document(self):
        self.publish({'FPF-Spec.md': CORE, 'maintenance.md': '# Maintenance DPF\n## ME.1 - First\nFirst.\n## ME.1 - Second\nzephyrneedle.\n'})
        hit = corpus.search(self.data, 'zephyrneedle')['results'][0]
        self.assertTrue(hit['selector'].endswith('::ME.1~2'))
        p = packets.packet(self.data, 'zephyrneedle')
        self.assertIn('zephyrneedle', p['sources'][0]['text'])
        self.assertNotIn('First.', p['sources'][0]['text'])

    def test_corrupt_cache_rebuilds_from_authoritative_source(self):
        first = packets.packet(self.data, 'ME.1')
        path = Path(first['cache_path'])
        record = json.loads(path.read_text(encoding='utf-8'))
        record['packet']['sources'][0]['text'] = 'wrong'
        corpus.atomic_json(path, record)
        again = packets.packet(self.data, 'ME.1')
        self.assertFalse(again['cache_hit'])
        self.assertIn('Inspect corrosion.', again['sources'][0]['text'])

    def test_refresh_during_packet_search_does_not_mix_versions(self):
        original = corpus.search
        def during_search(*args, **kwargs):
            self.publish({'FPF-Spec.md': CORE, 'maintenance.md': DPF.replace('corrosion', 'erosion')})
            return original(*args, **kwargs)
        with patch.object(corpus, 'search', side_effect=during_search):
            p = packets.packet(self.data, 'corrosion')
        self.assertEqual(p['snapshot'], self.old)
        self.assertIn('Inspect corrosion.', p['sources'][0]['text'])

    def test_cli_bound_pin_and_exit_status(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = corpus.main(['--data', str(self.data), '--snapshot', self.old,
                                'packet', 'ME.1', '--max-chars', '2400'])
        self.assertEqual(code, 0)
        self.assertLessEqual(len(output.getvalue()), 2400)
        self.assertEqual(json.loads(output.getvalue())['snapshot'], self.old)

    def test_selected_role_loads_just_its_own_instructions(self):
        preset = harness.role('scout')
        self.assertEqual(preset['instructions'], Path(preset['instruction_file']).read_text(encoding='utf-8'))
        self.assertNotEqual(harness.role('analyst')['reasoning_effort'], harness.role('analyst', True)['reasoning_effort'])
        with self.assertRaises(ValueError):
            harness.role('../expert')


if __name__ == '__main__':
    unittest.main()
