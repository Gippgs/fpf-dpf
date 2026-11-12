import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import corpus
import semantic
from fixtures import published

CORE = '# First Principles Framework\n\n## A.1 - Systems\nOwnership and responsibility.\n### A.1:1 - Problem\nSystem boundary.\n### A.1:End\n\n## C.19.2 - Use-Bounded Apparatus\nStop at sufficiency.\n'
DPF = '# Maintenance Principles Framework\n\n## ME.1 - Inspection\nInspect corrosion.\n## ME.2 - Repair\nRepair a pump.\n## ME.3 - Feedback\nLearn from failure.\n'


class CorpusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'data'
        self.files = {'FPF-Spec.md': CORE, 'Engineering/maintenance.md': DPF}

    def publish(self, files=None, commit='a' * 40):
        return corpus.publish(self.data, published(files or self.files), commit, 'test')

    def test_initial_core_dpf_search_read_and_citation(self):
        m = self.publish()
        self.assertEqual(m['counts']['patterns'], 5)
        self.assertEqual(corpus.read(self.data, 'C.19.2')['text'].splitlines()[-1].split(': ', 1)[1], 'Stop at sufficiency.')
        found = corpus.search(self.data, 'corrosion', kind='DPF')['results'][0]
        self.assertEqual(found['pid'], 'ME.1')
        self.assertIn('/' + 'a' * 40 + '/', found['url'])
        self.assertIn('corrosion', corpus.read(self.data, found['selector'])['text'])

    def test_dpf_only_update(self):
        first = self.publish()
        changed = dict(self.files, **{'Engineering/maintenance.md': DPF.replace('corrosion', 'erosion')})
        m = self.publish(changed, 'b' * 40)
        self.assertEqual(m['changes']['changed'], ['Engineering/maintenance.md'])
        self.assertTrue(corpus.search(self.data, 'erosion')['results'])
        self.assertFalse(corpus.search(self.data, 'corrosion')['results'])
        self.assertEqual(first['documents'][0]['id'], m['documents'][0]['id'])

    def test_new_dpf_in_new_directory(self):
        self.publish()
        files = self.files | {'New Suite/new.md': '# New DPF\n## NEW.1 - Test\nDistinct newdomain.\n'}
        m = self.publish(files)
        self.assertIn('New Suite/new.md', m['changes']['added'])
        self.assertEqual(corpus.search(self.data, 'newdomain')['results'][0]['pid'], 'NEW.1')

    def test_rename_exact_and_alias(self):
        old = self.publish()
        before = next(d for d in old['documents'] if d['kind'] == 'DPF')
        files = {'FPF-Spec.md': CORE, 'Renamed Suite/renamed.md': DPF}
        m = self.publish(files)
        renamed = next(d for d in m['documents'] if d['kind'] == 'DPF')
        self.assertEqual(before['id'], renamed['id'])
        self.assertEqual(corpus.read(self.data, 'Engineering/maintenance.md')['path'], 'Renamed Suite/renamed.md')

    def test_rename_and_edit_unique_pattern_signature(self):
        self.publish()
        m = self.publish({'FPF-Spec.md': CORE, 'Other/new-name.md': DPF + '\nUpdated context.\n'})
        self.assertEqual(len(m['changes']['renamed']), 1)
        self.assertEqual([p for p in m['changes']['changed'] if p != 'Readme.md'], ['Other/new-name.md'])

    def test_ambiguous_duplicate_rename_not_guessed(self):
        self.publish()
        m = self.publish({'FPF-Spec.md': CORE, 'x.md': DPF, 'y.md': DPF})
        self.assertEqual(m['changes']['renamed'], [])
        self.assertEqual(set(m['changes']['ambiguous']), {'x.md', 'y.md'})

    def test_delete_removed_from_search_old_snapshot_retained(self):
        self.publish()
        prior = corpus.current_snapshot(self.data)[0]
        m = self.publish({'FPF-Spec.md': CORE})
        self.assertIn('Engineering/maintenance.md', m['changes']['removed'])
        self.assertFalse(corpus.search(self.data, 'corrosion')['results'])
        self.assertTrue((prior / 'corpus.sqlite').is_file())

    def test_failed_database_build_preserves_pointer(self):
        self.publish()
        pointer = (self.data / 'current.json').read_bytes()
        with patch.object(corpus, 'make_database', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                self.publish()
        self.assertEqual(pointer, (self.data / 'current.json').read_bytes())
        self.assertIn('Systems', corpus.read(self.data, 'A.1')['title'])

    def test_missing_core_blocks_promotion(self):
        self.publish()
        pointer = (self.data / 'current.json').read_bytes()
        with self.assertRaises(ValueError):
            self.publish({'dpf.md': DPF})
        self.assertEqual(pointer, (self.data / 'current.json').read_bytes())

    def test_unrecognized_document_remains_searchable(self):
        self.publish(self.files | {'new-form.md': '# Novel Format\nRead zephyrneedle here.\n'})
        hit = corpus.search(self.data, 'zephyrneedle')['results'][0]
        self.assertEqual(hit['kind'], 'DOCUMENT')
        self.assertIn('zephyrneedle', corpus.read(self.data, hit['selector'])['text'])

    def test_no_patterns_dpf_visible_warning(self):
        m = self.publish(self.files | {'new-dpf.md': '# Another DPF\nChanged format.\n'})
        self.assertIn('new-dpf.md', m['warnings'])

    def test_headings_inside_fence_are_not_patterns(self):
        text = CORE + '\n```markdown\n## FAKE.1 - Ignore\n```\n'
        self.assertNotIn('FAKE.1', [s['pid'] for s in corpus.sections(text)])

    def test_mixed_case_and_hyphenated_ids_are_not_truncated(self):
        text = '\n'.join(['## C.2.2a - Chart', 'Body', '## A.19.SelectorMechanism - Select',
                          'Body', '## A.19.SOURCE-SET - Substrate', '### A.19.SOURCE-SET:1 - Use', 'Body'])
        self.assertEqual([s['pid'] for s in corpus.sections(text)], ['C.2.2a', 'A.19.SelectorMechanism', 'A.19.SOURCE-SET'])

    def test_readme_does_not_become_second_core(self):
        m = self.publish(self.files | {'Readme.md': '# First Principles Framework Ecosystem\nIntro'})
        self.assertEqual(sum(d['kind']=='FPF' for d in m['documents']), 1)

    def test_duplicate_ids_require_qualified_selector(self):
        self.publish(self.files | {'another.md': '# Other DPF\n## A.1 - Other meaning\nOther.\n'})
        self.assertEqual(corpus.read(self.data, 'A.1')['error'], 'ambiguous')

    def test_pagination_preserves_source_lines(self):
        self.publish()
        first = corpus.read(self.data, 'ME.1', lines=1)
        self.assertIsNotNone(first['next_line'])
        second = corpus.read(self.data, 'ME.1', start=first['next_line'], lines=2)
        self.assertIn('Inspect corrosion.', second['text'])
        self.assertNotIn('ME.2', second['text'])

    def test_query_punctuation_is_not_sql(self):
        self.publish()
        corpus.search(self.data, 'corrosion\"; DROP TABLE documents;--')
        self.assertIn('corrosion', corpus.read(self.data, 'ME.1')['text'])
        self.assertEqual(len(corpus.catalog(self.data)['documents']), 4)

    def test_path_traversal_archive_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('root/../../outside.md', 'bad')
        with self.assertRaises(ValueError):
            corpus.archive_files(data.getvalue())

    def test_network_failure_keeps_snapshot_reports_failure(self):
        self.publish()
        with patch.object(corpus, 'request_bytes', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                corpus.refresh(self.data)
        self.assertEqual(corpus.status(self.data)['state'], 'ready')
        self.assertEqual(corpus.status(self.data)['last_refresh']['error'], 'offline')

    def test_remote_dpf_only_change_fetches_full_new_commit(self):
        self.publish()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            for path, body in published({'FPF-Spec.md': CORE, 'Engineering/maintenance.md': DPF.replace('corrosion', 'erosion')}).items():
                archive.writestr('FPF-new/' + path, body)
        with patch.object(corpus, 'request_bytes', side_effect=[json.dumps({'sha': 'b'*40}).encode(), buf.getvalue()]) as net:
            result = corpus.refresh(self.data)
        self.assertEqual(result['state'], 'updated')
        self.assertEqual(result['changes']['changed'], ['Engineering/maintenance.md'])
        self.assertIn('b'*40, net.call_args_list[-1].args[0])
        self.assertTrue(corpus.search(self.data, 'erosion')['results'])

    def test_broken_remote_archive_retains_working_snapshot(self):
        self.publish()
        with patch.object(corpus, 'request_bytes', side_effect=[json.dumps({'sha':'b'*40}).encode(), b'broken']):
            with self.assertRaises(zipfile.BadZipFile):
                corpus.refresh(self.data)
        self.assertEqual(corpus.status(self.data)['commit'], 'a'*40)

    def test_each_new_task_checks_even_after_recent_success(self):
        self.publish()
        commit = json.dumps({'sha': 'a' * 40}).encode()
        with patch.object(corpus, 'request_bytes', return_value=commit) as network:
            self.assertEqual(corpus.refresh(self.data)['state'], 'unchanged')
            self.assertEqual(corpus.refresh(self.data, if_stale=True)['state'], 'unchanged')
            self.assertEqual(network.call_count, 2)
            corpus.refresh(self.data)
            self.assertEqual(network.call_count, 3)

    def test_offline_does_not_contact_network(self):
        with patch.object(corpus, 'request_bytes', side_effect=AssertionError('network')):
            self.assertEqual(corpus.refresh(self.data, offline=True)['state'], 'offline')

    def test_lock_blocks_concurrent_update(self):
        with corpus.update_lock(self.data):
            with self.assertRaises(RuntimeError):
                with corpus.update_lock(self.data):
                    pass
        self.assertFalse((self.data / 'update.lock').exists())

    def test_semantic_snapshot_invalidation(self):
        self.publish()
        folder, _ = corpus.current_snapshot(self.data)
        corpus.atomic_json(self.data / 'semantic/manifest.json', {'snapshot': folder.name, 'vectors': 'a'*32+'.npy'})
        self.assertEqual(semantic.available_index(self.data)['snapshot'], folder.name)
        self.publish(self.files | {'new.md': '# New DPF\n## NEW.1 - Added\nAdded.\n'})
        with self.assertRaises(ValueError):
            semantic.available_index(self.data)

    def test_semantic_index_build_search_and_read_contract(self):
        import numpy as np

        class TestEncoder:
            def encode(self, texts, **kwargs):
                return np.array([[1., 0.] if 'corrosion' in t else [0., 1.] for t in texts])

        self.publish()
        encoder = TestEncoder()
        built = semantic.build(self.data, encoder, np, 'test-encoder')
        self.assertGreater(built['vectors'], 0)
        hit = semantic.search(self.data, 'corrosion', encoder, np, 1)['results'][0]
        self.assertEqual(hit['pid'], 'ME.1')
        self.assertIn('corrosion', corpus.read(self.data, hit['selector'])['text'])

    def test_core_filename_rename_preserves_identity(self):
        m = self.publish()
        old = next(d for d in m['documents'] if d['kind'] == 'FPF')['id']
        renamed = self.publish({'Core-renamed.md': CORE, 'Engineering/maintenance.md': DPF})
        self.assertEqual(next(d for d in renamed['documents'] if d['kind'] == 'FPF')['id'], old)

    def test_exact_search_obeys_domain_filter(self):
        self.publish(self.files | {'another.md': '# Other DPF\n## A.1 - Domain meaning\nOther.\n'})
        hits = corpus.search(self.data, 'A.1', kind='DPF')['results']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['kind'], 'DPF')

    def test_ten_routes_preserved(self):
        self.publish()
        result = corpus.routes(self.data)
        self.assertEqual(len(result['routes']), 10)
        self.assertTrue(all(r['patterns'] for r in result['routes']))


if __name__ == '__main__':
    unittest.main()
