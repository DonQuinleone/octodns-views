#
#
#

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from os.path import dirname, join
from shutil import rmtree
from tempfile import mkdtemp
from unittest import TestCase

SCRIPT = join(dirname(dirname(__file__)), 'script', 'update-readme-pins')
loader = SourceFileLoader('update_readme_pins', SCRIPT)
update_readme_pins = module_from_spec(spec_from_loader(loader.name, loader))
loader.exec_module(update_readme_pins)

OLD_SHA = 'a' * 40
NEW_OCTODNS_SHA = 'b' * 40
NEW_VIEWS_SHA = 'c' * 40

README = f'''## Installation

```
octodns==1.20.0
octodns-views==0.9.0
```

```
-e git+https://git@github.com/octodns/octodns.git@{OLD_SHA}#egg=octodns
-e git+https://git@github.com/DonQuinleone/octodns-views.git@{OLD_SHA}#egg=octodns_views
```
'''


class TestUpdateReadmePins(TestCase):
    def pins(self):
        return update_readme_pins.Pins(
            octodns_version='1.22.0',
            octodns_sha=NEW_OCTODNS_SHA,
            version='1.0.0',
            sha=NEW_VIEWS_SHA,
        )

    def test_rewrites_every_pin(self):
        updated = update_readme_pins.apply(README, self.pins())

        self.assertIn('\noctodns==1.22.0\n', updated)
        self.assertIn('\noctodns-views==1.0.0\n', updated)
        self.assertIn(f'octodns.git@{NEW_OCTODNS_SHA}#egg=octodns\n', updated)
        self.assertIn(
            f'octodns-views.git@{NEW_VIEWS_SHA}#egg=octodns_views', updated
        )
        self.assertNotIn(OLD_SHA, updated)

    def test_leaves_the_rest_alone(self):
        updated = update_readme_pins.apply(README, self.pins())

        self.assertTrue(updated.startswith('## Installation\n\n```\n'))
        self.assertEqual(README.count('\n'), updated.count('\n'))

    def test_fails_when_a_pin_is_missing(self):
        readme = README.replace('octodns-views==0.9.0\n', '')

        with self.assertRaises(update_readme_pins.PinNotFound) as ctx:
            update_readme_pins.apply(readme, self.pins())

        self.assertEqual(
            'README.md has no octodns-views version pin to update',
            str(ctx.exception),
        )

    def test_main_rewrites_the_file(self):
        path = join(self.tmp(), 'README.md')
        with open(path, 'w') as fh:
            fh.write(README)

        update_readme_pins.main(
            [
                '--readme',
                path,
                '--octodns-version',
                '1.22.0',
                '--octodns-sha',
                NEW_OCTODNS_SHA,
                '--version',
                '1.0.0',
                '--sha',
                NEW_VIEWS_SHA,
            ]
        )

        with open(path) as fh:
            self.assertIn('octodns-views==1.0.0', fh.read())

    def test_main_rejects_a_short_sha(self):
        with self.assertRaises(SystemExit):
            update_readme_pins.main(
                [
                    '--octodns-version',
                    '1.22.0',
                    '--octodns-sha',
                    'abc123',
                    '--version',
                    '1.0.0',
                    '--sha',
                    NEW_VIEWS_SHA,
                ]
            )

    def test_main_rejects_an_unsafe_version(self):
        for version in ('1.22.0\n-e git+https://evil.example/x.git', 'a b', ''):
            with self.subTest(version=version):
                with self.assertRaises(SystemExit):
                    update_readme_pins.main(
                        [
                            '--octodns-version',
                            version,
                            '--octodns-sha',
                            NEW_OCTODNS_SHA,
                            '--version',
                            '1.0.0',
                            '--sha',
                            NEW_VIEWS_SHA,
                        ]
                    )

    def test_replacements_are_literal(self):
        pins = update_readme_pins.Pins(
            octodns_version=r'1.22.0\g<0>',
            octodns_sha=NEW_OCTODNS_SHA,
            version='1.0.0',
            sha=NEW_VIEWS_SHA,
        )

        updated = update_readme_pins.apply(README, pins)

        self.assertIn('\noctodns==1.22.0\\g<0>\n', updated)

    def tmp(self):
        directory = mkdtemp()
        self.addCleanup(rmtree, directory)
        return directory
