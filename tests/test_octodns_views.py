from logging import getLogger
from os import makedirs
from os.path import join
from tempfile import TemporaryDirectory
from unittest import TestCase

from yaml import safe_dump, safe_load

from octodns.manager import Manager
from octodns.processor.base import ProcessorException
from octodns.provider import SupportsException
from octodns.provider.base import BaseProvider
from octodns.record import Record
from octodns.zone import Zone

from octodns_views import Views

ZONE = 'example.com.'


class FakeTarget(BaseProvider):
    SUPPORTS = {'A', 'AAAA', 'CNAME', 'TXT'}
    SUPPORTS_GEO = False
    SUPPORTS_DYNAMIC = False

    def __init__(self, id, strict_supports=True, supports=None):
        self.log = getLogger(f'FakeTarget[{id}]')
        super().__init__(id, strict_supports=strict_supports)
        if supports is not None:
            self.SUPPORTS = supports


def zone_with(records):
    zone = Zone(ZONE, [])
    for name, data in records.items():
        zone.add_record(Record.new(zone, name, data))
    return zone


def by_name(zone):
    return {(record.name, record._type): record for record in zone.records}


def plan_for(processor, desired, target):
    if isinstance(target, str):
        target = FakeTarget(target)
    desired = desired.copy()
    existing = Zone(ZONE, [])
    return processor.process_source_and_target_zones(desired, existing, target)


def with_views(base, **views):
    return dict(base, octodns={'views': views})


ABS = {
    'type': 'CNAME',
    'ttl': 300,
    'value': 'edge.example.net.',
    'octodns': {'views': {'inside': {'type': 'A', 'value': '192.0.2.5'}}},
}
WWW = {
    'type': 'A',
    'ttl': 3600,
    'value': '198.51.100.1',
    'octodns': {'views': {'inside': {'value': '192.0.2.1'}}},
}
PLAIN = {'type': 'A', 'ttl': 3600, 'value': '198.51.100.9'}


class TestConfig(TestCase):
    def test_rejects_a_target_in_two_views(self):
        with self.assertRaises(ProcessorException) as ctx:
            Views('views', views={'inside': ['dns1'], 'lab': ['dns1']})
        self.assertIn('dns1', str(ctx.exception))

    def test_rejects_views_that_are_not_a_mapping(self):
        with self.assertRaises(ProcessorException):
            Views('views', views=['inside'])

    def test_rejects_a_view_without_a_target_list(self):
        for targets in ('dns1', [], [1]):
            with self.assertRaises(ProcessorException):
                Views('views', views={'inside': targets})


class TestSourceZone(TestCase):
    def setUp(self):
        self.processor = Views('views', views={'inside': ['dns1']})

    def test_accepts_valid_overrides(self):
        desired = zone_with({'abs': ABS, 'www': WWW, 'plain': PLAIN})
        self.assertIs(
            desired, self.processor.process_source_zone(desired, sources=[])
        )

    def test_rejects_an_override_naming_an_unknown_view(self):
        record = dict(WWW, octodns={'views': {'outside': {'value': '1.2.3.4'}}})
        with self.assertRaises(ProcessorException) as ctx:
            self.processor.process_source_zone(
                zone_with({'www': record}), sources=[]
            )
        self.assertIn('outside', str(ctx.exception))
        self.assertIn('www.example.com.', str(ctx.exception))

    def test_rejects_an_invalid_override(self):
        record = dict(WWW, octodns={'views': {'inside': {'value': 'nope'}}})
        with self.assertRaises(ProcessorException) as ctx:
            self.processor.process_source_zone(
                zone_with({'www': record}), sources=[]
            )
        self.assertIn('www.example.com.', str(ctx.exception))

    def test_rejects_views_that_are_not_a_mapping(self):
        record = dict(WWW, octodns={'views': ['inside']})
        with self.assertRaises(ProcessorException):
            self.processor.process_source_zone(
                zone_with({'www': record}), sources=[]
            )

    def test_rejects_an_override_that_is_not_a_mapping(self):
        record = dict(WWW, octodns={'views': {'inside': '192.0.2.1'}})
        with self.assertRaises(ProcessorException):
            self.processor.process_source_zone(
                zone_with({'www': record}), sources=[]
            )

    def test_rejects_an_override_that_breaks_cname_coexistence(self):
        records = {
            'app': with_views(
                PLAIN, inside={'type': 'CNAME', 'value': 'x.example.net.'}
            ),
            '': {'type': 'TXT', 'ttl': 3600, 'value': 'apex'},
        }
        records['app-v6'] = {
            'type': 'AAAA',
            'ttl': 3600,
            'value': '2001:db8::1',
        }
        zone = zone_with(records)
        zone.add_record(
            Record.new(
                zone,
                'app',
                {'type': 'AAAA', 'ttl': 3600, 'value': '2001:db8::1'},
            )
        )
        with self.assertRaises(ProcessorException) as ctx:
            self.processor.process_source_zone(zone, sources=[])
        self.assertIn('inside', str(ctx.exception))

    def test_rejects_an_override_that_collides_with_a_record(self):
        zone = zone_with(
            {'app': with_views(PLAIN, inside={'type': 'TXT', 'value': 'x'})}
        )
        zone.add_record(
            Record.new(zone, 'app', {'type': 'TXT', 'ttl': 3600, 'value': 'y'})
        )
        with self.assertRaises(ProcessorException) as ctx:
            self.processor.process_source_zone(zone, sources=[])
        self.assertIn('app.example.com.', str(ctx.exception))
        self.assertIn('inside', str(ctx.exception))

    def test_rejects_octodns_settings_in_an_override(self):
        record = with_views(
            WWW, inside={'value': '192.0.2.1', 'octodns': {'excluded': ['x']}}
        )
        with self.assertRaises(ProcessorException) as ctx:
            self.processor.process_source_zone(zone_with({'www': record}), [])
        self.assertIn('octodns', str(ctx.exception))

    def test_lenient_allows_an_invalid_override(self):
        override = {'type': 'CNAME', 'value': 'edge'}
        record = dict(WWW, octodns={'views': {'inside': override}})
        desired = zone_with({'www': record})
        with self.assertRaises(ProcessorException):
            self.processor.process_source_zone(desired, sources=[])
        processor = Views('views', views={'inside': ['dns1']}, lenient=True)
        self.assertIs(desired, processor.process_source_zone(desired, []))


class TestTargetZones(TestCase):
    def setUp(self):
        self.processor = Views('views', views={'inside': ['dns1', 'dns2']})
        self.desired = zone_with({'abs': ABS, 'www': WWW, 'plain': PLAIN})

    def test_replaces_a_same_type_override(self):
        desired, _ = plan_for(self.processor, self.desired, 'dns1')
        www = by_name(desired)[('www', 'A')]
        self.assertEqual(['192.0.2.1'], www.values)
        self.assertEqual(3600, www.ttl)

    def test_changes_the_type_for_an_override(self):
        desired, _ = plan_for(self.processor, self.desired, 'dns2')
        records = by_name(desired)
        self.assertNotIn(('abs', 'CNAME'), records)
        self.assertEqual(['192.0.2.5'], records[('abs', 'A')].values)

    def test_override_inherits_the_ttl_unless_it_sets_one(self):
        desired, _ = plan_for(self.processor, self.desired, 'dns1')
        self.assertEqual(300, by_name(desired)[('abs', 'A')].ttl)
        record = dict(WWW, octodns={'views': {'inside': {'ttl': 60}}})
        record['octodns']['views']['inside']['value'] = '192.0.2.1'
        desired, _ = plan_for(
            self.processor, zone_with({'www': record}), 'dns1'
        )
        self.assertEqual(60, by_name(desired)[('www', 'A')].ttl)

    def test_override_drops_the_views_but_keeps_other_octodns_settings(self):
        record = dict(WWW)
        record['octodns'] = dict(WWW['octodns'], ignored=False)
        desired, _ = plan_for(
            self.processor, zone_with({'www': record}), 'dns1'
        )
        self.assertEqual(
            {'ignored': False}, by_name(desired)[('www', 'A')].octodns
        )

    def test_leaves_records_without_an_override(self):
        desired, _ = plan_for(self.processor, self.desired, 'dns1')
        self.assertEqual(
            ['198.51.100.9'], by_name(desired)[('plain', 'A')].values
        )

    def test_leaves_a_target_outside_every_view_unchanged(self):
        desired, _ = plan_for(self.processor, self.desired, 'public')
        records = by_name(desired)
        self.assertEqual(
            ['edge.example.net.'], [records[('abs', 'CNAME')].value]
        )
        self.assertEqual(['198.51.100.1'], records[('www', 'A')].values)

    def test_does_not_change_the_source_zone_or_its_records(self):
        plan_for(self.processor, self.desired, 'dns1')
        records = by_name(self.desired)
        self.assertIn(('abs', 'CNAME'), records)
        self.assertEqual(['198.51.100.1'], records[('www', 'A')].values)

    def test_swaps_types_between_records_at_one_name(self):
        zone = zone_with(
            {
                'app': with_views(
                    PLAIN, inside={'type': 'AAAA', 'value': '2001:db8::5'}
                )
            }
        )
        zone.add_record(
            Record.new(
                zone,
                'app',
                with_views(
                    {'type': 'AAAA', 'ttl': 3600, 'value': '2001:db8::1'},
                    inside={'type': 'A', 'value': '192.0.2.9'},
                ),
            )
        )
        self.processor.process_source_zone(zone, sources=[])
        desired, _ = plan_for(self.processor, zone, 'dns1')
        records = by_name(desired)
        self.assertEqual(['192.0.2.9'], records[('app', 'A')].values)
        self.assertEqual(['2001:db8::5'], records[('app', 'AAAA')].values)

    def test_strips_views_from_records_for_every_target(self):
        for target in ('dns1', 'public'):
            desired, _ = plan_for(self.processor, self.desired, target)
            for record in desired.records:
                self.assertNotIn('views', record.octodns, (target, record.name))

    def test_strict_target_rejects_an_override_type_it_does_not_support(self):
        target = FakeTarget('dns1', supports={'A', 'CNAME'})
        zone = zone_with(
            {'www': with_views(WWW, inside={'type': 'TXT', 'value': 'x'})}
        )
        with self.assertRaises(SupportsException):
            plan_for(self.processor, zone, target)

    def test_lax_target_drops_an_override_type_it_does_not_support(self):
        target = FakeTarget(
            'dns1', strict_supports=False, supports={'A', 'CNAME'}
        )
        zone = zone_with(
            {'www': with_views(WWW, inside={'type': 'TXT', 'value': 'x'})}
        )
        desired, _ = plan_for(self.processor, zone, target)
        self.assertEqual([], [r for r in desired.records if r.name == 'www'])

    def test_strict_target_rejects_a_dynamic_override(self):
        override = {
            'value': '192.0.2.1',
            'dynamic': {
                'pools': {'one': {'values': [{'value': '192.0.2.2'}]}},
                'rules': [{'pool': 'one'}],
            },
        }
        zone = zone_with({'www': with_views(WWW, inside=override)})
        with self.assertRaises(SupportsException):
            plan_for(self.processor, zone, 'dns1')

    def test_returns_the_existing_zone_untouched(self):
        existing = Zone(ZONE, [])
        _, returned = self.processor.process_source_and_target_zones(
            self.desired.copy(), existing, FakeTarget('dns1')
        )
        self.assertIs(existing, returned)


class TestManager(TestCase):
    def test_sync_gives_each_target_its_own_view(self):
        with TemporaryDirectory() as tmp:
            zones = join(tmp, 'zones')
            config = {
                'providers': {
                    'config': {
                        'class': 'octodns.provider.yaml.YamlProvider',
                        'escaped_semicolons': False,
                        'directory': zones,
                    },
                    'outside': {
                        'class': 'octodns.provider.yaml.YamlProvider',
                        'escaped_semicolons': False,
                        'directory': join(tmp, 'outside'),
                    },
                    'inside': {
                        'class': 'octodns.provider.yaml.YamlProvider',
                        'escaped_semicolons': False,
                        'directory': join(tmp, 'inside'),
                    },
                },
                'processors': {
                    'views': {
                        'class': 'octodns_views.Views',
                        'views': {'inside': ['inside']},
                    }
                },
                'zones': {
                    ZONE: {
                        'sources': ['config'],
                        'processors': ['views'],
                        'targets': ['outside', 'inside'],
                    }
                },
            }
            makedirs(zones)
            with open(join(zones, f'{ZONE}yaml'), 'w') as fh:
                safe_dump({'abs': ABS, 'www': WWW}, fh)
            config_file = join(tmp, 'config.yaml')
            with open(config_file, 'w') as fh:
                safe_dump(config, fh)

            Manager(config_file).sync(dry_run=False)

            with open(join(tmp, 'outside', f'{ZONE}yaml')) as fh:
                outside = safe_load(fh)
            with open(join(tmp, 'inside', f'{ZONE}yaml')) as fh:
                inside = safe_load(fh)

        self.assertEqual('CNAME', outside['abs']['type'])
        self.assertEqual('198.51.100.1', outside['www']['value'])
        self.assertEqual('A', inside['abs']['type'])
        self.assertEqual('192.0.2.5', inside['abs']['value'])
        self.assertEqual('192.0.2.1', inside['www']['value'])
