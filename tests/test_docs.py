'''Keep the docs honest: the split-horizon example syncs as the guide says, the
guide quotes the example files verbatim, and every YAML block in the docs
parses.'''

import re
from glob import glob
from os.path import dirname, join
from tempfile import TemporaryDirectory
from unittest import TestCase

from octodns_katapult import KatapultProvider
from octodns_powerdns import PowerDnsProvider
from yaml import safe_dump, safe_load

from octodns.manager import Manager
from octodns.provider.yaml import YamlProvider
from octodns.yaml import safe_load as ordered_load

ROOT = dirname(dirname(__file__))
DOCS = join(ROOT, 'docs')
EXAMPLE = join(DOCS, 'examples', 'split-horizon')
GUIDE = join(DOCS, 'split-horizon-katapult-powerdns.md')
ZONE = 'example.com.'
CONFIG_KEYS = {'manager', 'processors', 'providers', 'zones'}
YAML_BLOCK = re.compile(r'^```yaml\n(.*?)^```', re.MULTILINE | re.DOTALL)


class KatapultStandIn(YamlProvider):
    '''A YAML target that accepts only what Katapult supports.'''

    SUPPORTS = KatapultProvider.SUPPORTS
    SUPPORTS_DYNAMIC = False


class PowerDnsStandIn(YamlProvider):
    '''A YAML target that accepts only what PowerDNS supports.'''

    SUPPORTS = PowerDnsProvider.SUPPORTS
    SUPPORTS_DYNAMIC = False


def read(path):
    with open(path) as fh:
        return fh.read()


def sync_example(tmp):
    config = safe_load(read(join(EXAMPLE, 'config.yaml')))
    providers = config['providers']
    providers['config']['directory'] = join(EXAMPLE, 'zones')
    for name, stand_in in (
        ('katapult', KatapultStandIn),
        ('powerdns', PowerDnsStandIn),
    ):
        providers[name] = {
            'class': f'{__name__}.{stand_in.__name__}',
            'directory': join(tmp, name),
            'escaped_semicolons': False,
        }
    config_file = join(tmp, 'config.yaml')
    with open(config_file, 'w') as fh:
        safe_dump(config, fh)
    Manager(config_file).sync(dry_run=False)
    return {
        name: safe_load(read(join(tmp, name, f'{ZONE}yaml')))
        for name in ('katapult', 'powerdns')
    }


class TestSplitHorizonExample(TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as tmp:
            zones = sync_example(tmp)
        cls.outside = zones['katapult']
        cls.inside = zones['powerdns']

    def test_outside_gets_the_records_as_written(self):
        self.assertEqual(
            {'type': 'ALIAS', 'value': 'edge.example.net.'}, self.outside['']
        )
        self.assertEqual('CNAME', self.outside['app']['type'])
        self.assertEqual('status.example.org.', self.outside['status']['value'])

    def test_inside_gets_the_overrides(self):
        self.assertEqual({'type': 'A', 'value': '192.0.2.10'}, self.inside[''])
        self.assertEqual(
            {'type': 'A', 'ttl': 300, 'value': '192.0.2.10'}, self.inside['app']
        )

    def test_included_and_excluded_names_reach_one_side(self):
        self.assertIn('nas', self.inside)
        self.assertNotIn('nas', self.outside)
        self.assertIn('status', self.outside)
        self.assertNotIn('status', self.inside)

    def test_shared_names_match_on_both_sides(self):
        for name in ('mail', 'www'):
            self.assertEqual(self.outside[name], self.inside[name])

    def test_no_side_receives_the_views_data(self):
        for zone in (self.outside, self.inside):
            for name, record in zone.items():
                self.assertNotIn('views', record.get('octodns', {}), name)


class TestDocs(TestCase):
    def test_guide_quotes_the_example_files_verbatim(self):
        guide = read(GUIDE)
        blocks = YAML_BLOCK.findall(guide)
        for path in (
            join(EXAMPLE, 'config.yaml'),
            join(EXAMPLE, 'zones', f'{ZONE}yaml'),
        ):
            self.assertIn(read(path), blocks, path)

    def test_every_yaml_block_in_the_docs_parses(self):
        # Record snippets load as a zone file does with enforce_order, which
        # is YamlProvider's default, so they can be copied as they are.
        paths = glob(join(DOCS, '*.md')) + [join(ROOT, 'README.md')]
        self.assertGreater(len(paths), 2)
        for path in paths:
            for block in YAML_BLOCK.findall(read(path)):
                with self.subTest(path=path, block=block[:40]):
                    data = safe_load(block)
                    if not CONFIG_KEYS & set(data):
                        ordered_load(block, enforce_order=True)
