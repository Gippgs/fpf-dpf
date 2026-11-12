import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import corpus
from publications import select_publications
from fixtures import published

CORE = '# First Principles Framework\n## A.1 - System\nSystem boundary.\n'
DPF = '# Example DPF\n## NEW.1 - Decide\nPublishedneedle.\n'


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.files = published({'FPF-Spec.md': CORE})
        self.files['Readme.md'] += '| [Suite](./New%20Suite/) | Published |\n'
        self.files.update({
            'New Suite/README.md': '# Suite\n## Published DPFs\n| Question | DPF | Result |\n| --- | --- | --- |\n| Decide | [Method](method.md) | Choice |\n\n[Suite Reference](reference.md)\n',
            'New Suite/method.md': DPF + '\n[Earlier draft](../draft.md)\n',
            'New Suite/reference.md': '# Suite Reference\nConnected methods.\n',
            'draft.md': '# Draft DPF\n## DRAFT.1 - Draft\nDraftneedle.\n',
            'history/old.md': CORE.replace('boundary', 'oldneedle'),
            'LICENSE': 'Attribution',
        })

    def publish(self, files=None):
        return corpus.publish(self.data, self.files if files is None else files, 'a' * 40, 'test')

    def test_only_inventory_publications_and_references_are_searchable(self):
        self.files['Readme.md'] += '\n## Development notes\n[Draft](draft.md)\n'
        manifest = self.publish()
        self.assertEqual(manifest['publication_scope']['excluded_paths'], ['draft.md', 'history/old.md'])
        self.assertTrue(corpus.search(self.data, 'Publishedneedle')['results'])
        self.assertFalse(corpus.search(self.data, 'Draftneedle')['results'])
        self.assertFalse(corpus.search(self.data, 'oldneedle')['results'])
        self.assertIn('Connected methods.', corpus.read(self.data, 'New Suite/reference.md')['text'])
        self.assertEqual(corpus.read(self.data, 'draft.md')['error'], 'not_found')

    def test_declared_draft_status_is_excluded(self):
        self.files['Readme.md'] += '| [Draft](draft.md) | Draft |\n'
        self.assertNotIn('draft.md', select_publications(self.files)[0])

    def test_current_task_oriented_catalogues_select_only_declared_publications(self):
        files = {
            'Readme.md': ('# FPF Library\n## How the Library is organized and why\n'
                          '[Read the Library Architectural Reference](FPF-LIBRARY-REFERENCE.md).\n'
                          '## What is available\n| DPF Suite | Subject |\n| --- | --- |\n'
                          '| [Engineering](DPFs/Engineering%20DPF%20Suite/) | Systems |\n'
                          'The [DPF catalogue](DPFs/) lists further frameworks.\n'
                          '## Read online or use your own copies\n'
                          '[Core Markdown file and its history](FPF-Spec.md).\n'
                          '## Development notes\n[Unlisted](unlisted.md)\n'),
            'USING-FPF.md': '# Guide\n', 'FPF-Spec.md': CORE,
            'FPF-LIBRARY-REFERENCE.md': '# Library Reference\n',
            'DPFs/README.md': ('# DPFs\n## How the frameworks fit together\n'
                               '[Read the Library Architectural Reference](../FPF-LIBRARY-REFERENCE.md).\n'
                               '## Suites\n| Suite | Subject |\n| --- | --- |\n'
                               '| [Engineering](Engineering%20DPF%20Suite/) | Systems |\n'
                               '## Further domain frameworks\n| Framework | Subject |\n| --- | --- |\n'
                               '| [Published](https://fpf.tools/NEW) · [Markdown](published.md) | Work |\n'
                               '## Drafts\n| [Draft](drafts/future.md) | Work |\n'),
            'DPFs/published.md': DPF,
            'DPFs/Engineering DPF Suite/README.md': (
                '# Engineering\n## How this Suite is organized and why\n'
                '[Read the Engineering Architectural Reference](ENGINEERING-DPF-SUITE-REFERENCE.md).\n'
                '## Constituent DPFs and their different contributions\n'
                '| Framework | Subject |\n| --- | --- |\n'
                '| [Method](https://fpf.tools/ENG) · [Markdown](method.md) | Work |\n'
                '| [Historical](historical/old.md) | Past |\n'),
            'DPFs/Engineering DPF Suite/ENGINEERING-DPF-SUITE-REFERENCE.md': '# Reference\n',
            'DPFs/Engineering DPF Suite/method.md': '# Method\n',
            'DPFs/Engineering DPF Suite/historical/old.md': '# Old\n',
            'DPFs/drafts/future.md': '# Future\n', 'unlisted.md': '# Unlisted\n',
        }
        selected, scope = select_publications(files)
        self.assertEqual(set(selected), set(files) - {
            'unlisted.md', 'DPFs/drafts/future.md',
            'DPFs/Engineering DPF Suite/historical/old.md'})
        self.assertEqual(len(scope['catalogs']), 3)
        broken = dict(files)
        broken['DPFs/README.md'] = broken['DPFs/README.md'].replace(
            '## Further domain frameworks', '## Other fields')
        with self.assertRaisesRegex(ValueError, 'Incomplete public DPF catalogue'):
            select_publications(broken)

    def test_unlisted_new_file_waits_for_publication(self):
        self.files['New Suite/new.md'] = '# New DPF\n## OTHER.1 - Other\nFuturemethod.\n'
        self.publish()
        self.assertFalse(corpus.search(self.data, 'Futuremethod')['results'])
        self.files['New Suite/README.md'] += '| Other | [New](new.md) | Result |\n'
        self.publish()
        self.assertTrue(corpus.search(self.data, 'Futuremethod')['results'])

    def test_new_suite_and_rename_follow_updated_inventories(self):
        old = self.publish()
        old_id = next(d['id'] for d in old['documents'] if d['path'] == 'New Suite/method.md')
        self.files['New Suite/renamed.md'] = self.files.pop('New Suite/method.md')
        self.files['New Suite/README.md'] = self.files['New Suite/README.md'].replace('(method.md)', '(renamed.md)')
        self.files['Readme.md'] += '| [Another Suite](Other/README.md) | Published |\n'
        self.files['Other/README.md'] = '# Other\n## Publications\n| [Independent](domain.md) | Published |\n'
        self.files['Other/domain.md'] = '# Other DPF\n## OTHER.1 - Do\nOtherneedle.\n'
        self.publish()
        self.assertEqual(corpus.read(self.data, 'New Suite/method.md')['path'], 'New Suite/renamed.md')
        self.assertEqual(corpus.read(self.data, old_id)['path'], 'New Suite/renamed.md')
        self.assertTrue(corpus.search(self.data, 'Otherneedle')['results'])

    def test_broken_inventory_or_missing_guide_never_promotes(self):
        self.publish()
        pointer = (self.data / 'current.json').read_bytes()
        mutations = [
            {'New Suite/README.md': '# Unsupported catalog\n'},
            {'New Suite/README.md': '# Suite\n## Publications\n[No table](method.md)\n'},
            {'New Suite/README.md': '# Suite\n## Publications\n| [Missing](missing.md) | Published |\n'},
            {'USING-FPF.md': ''},
            {'Readme.md': '# Readme\n## Publications\n| [Core][core] | Published |\n[core]: FPF-Spec.md'},
        ]
        for changes in mutations:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.publish(self.files | changes)
            self.assertEqual(pointer, (self.data / 'current.json').read_bytes())
        without = dict(self.files)
        del without['USING-FPF.md']
        with self.assertRaises(ValueError):
            self.publish(without)

    def test_absolute_github_and_parent_links_resolve_in_same_copy(self):
        self.files['New Suite/README.md'] += '| Core | [Core](https://github.com/ailev/FPF/blob/main/FPF-Spec.md#anchor) | Result |\n| Core | [Core](../FPF-Spec.md) | Result |\n'
        with patch.object(corpus, 'request_bytes', side_effect=AssertionError('network')):
            self.publish()
        self.assertEqual(corpus.read(self.data, 'A.1')['commit'], 'a' * 40)

    def test_traversal_in_inventory_is_rejected(self):
        self.files['Readme.md'] += '| [Outside](../outside.md) | Published |\n'
        with self.assertRaisesRegex(ValueError, 'Unsafe inventory'):
            self.publish()

    def test_guide_hash_and_pagination_remain_pinned(self):
        self.files['USING-FPF.md'] = '# Guide\n' + '\n'.join('Instruction ' + str(n) for n in range(700))
        self.publish()
        before = corpus.status(self.data)
        first = corpus.read(self.data, 'USING-FPF.md', lines=500, snapshot=before['snapshot'])
        self.assertTrue(first['partial'])
        self.assertEqual(first['next_line'], 501)
        self.files['USING-FPF.md'] = '# Revised guide\nChanged instruction.\n'
        self.publish()
        after = corpus.status(self.data)
        self.assertNotEqual(before['usage_guide']['hash'], after['usage_guide']['hash'])
        last = corpus.read(self.data, 'USING-FPF.md', start=501, lines=500, snapshot=before['snapshot'])
        self.assertIsNone(last['next_line'])
        self.assertIn('Instruction 699', last['text'])
        self.assertEqual(corpus.status(self.data, before['snapshot'])['usage_guide'], before['usage_guide'])

    def test_migration_rebuilds_unchanged_commit(self):
        self.publish()
        folder, manifest = corpus.current_snapshot(self.data)
        manifest['schema'] = 1
        manifest.pop('publication_scope')
        corpus.atomic_json(folder / 'manifest.json', manifest)
        self.assertEqual(corpus.status(self.data)['publication_scope']['policy'], 'legacy-unfiltered')
        with patch.object(corpus, 'request_bytes', side_effect=[json.dumps({'sha': 'a' * 40}).encode(), b'archive']) as net, patch.object(corpus, 'archive_files', return_value=self.files):
            result = corpus.refresh(self.data)
        self.assertEqual(net.call_count, 2)
        self.assertEqual(result['state'], 'updated')
        self.assertEqual(corpus.status(self.data)['publication_scope']['policy'], 'public-readme-inventories-v1')

    def test_recent_failure_is_not_misreported_as_fresh(self):
        self.publish()
        corpus.atomic_json(self.data / 'refresh.json', {'error': 'offline', 'attempt_epoch': time.time()})
        with patch.object(corpus, 'request_bytes', return_value=json.dumps({'sha': 'a' * 40}).encode()) as net:
            self.assertEqual(corpus.refresh(self.data, if_stale=True)['state'], 'retry_deferred')
            self.assertEqual(net.call_count, 0)
            self.assertEqual(corpus.refresh(self.data)['state'], 'unchanged')
            self.assertEqual(net.call_count, 1)
        self.assertIsNone(corpus.status(self.data)['last_refresh']['error'])


if __name__ == '__main__':
    unittest.main()
