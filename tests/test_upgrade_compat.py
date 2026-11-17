"""Exercise recognized UULink upgrades inside a disposable router filesystem."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


AGENT = Path(__file__).resolve().parents[1]
FILES = {
    'init': ('files/etc/init.d/uulink', 'etc/init.d/uulink'),
    'sampler': ('files/usr/libexec/uulink/sampler.uc', 'usr/libexec/uulink/sampler.uc'),
    'plugin': ('files/usr/share/rpcd/ucode/uulink.uc', 'usr/share/rpcd/ucode/uulink.uc'),
    'acl': ('files/usr/share/rpcd/acl.d/uulink.json', 'usr/share/rpcd/acl.d/uulink-agent.json'),
    'menu': ('files/usr/share/luci/menu.d/luci-app-uulink.json', 'usr/share/luci/menu.d/luci-app-uulink.json'),
    'view': ('files/www/luci-static/resources/view/uulink/index.js', 'www/luci-static/resources/view/uulink/index.js'),
}
OLD_HASHES = {
    'v01_plugin': 'e8d4cab08b853be6d0c343feba9f537c2739e80911faf0a79cbd52f4d44c34fc',
    'v01_acl': 'afc7a8e75862a4e4ccd1b8b0e7dbded28f24bb4de458c6ba40c06d3ad7911d84',
    'snapshot_plugin': 'd72bae01a6def9c8c1d77182ee6a2f8a4f6e9f645a089345e8076d774b32cbfa',
    'snapshot_acl': 'a48da02515324a58194f9222213e9f2ea588307f1afe185f7fe389a2e7633e45',
    'v01_sampler': '69d37cbfcc6663afc1cdfde5d571aa31bed704b8876173b3666e889d5e905c98',
    'v02_sampler': 'a408a9e330cf2ed56ef7d68a70f0998cd1f9cd3dbe6ebddb460fd606b30d7a10',
    'u30air_sampler': '84ae744755fa8ed4fca22ed0b203593770ef50d5b7b0e719b4c8908b3212bffa',
    'f50_sampler': '85602207f701a0efd7eca4413a44eaf25ba594ce38645f0b59078384745aa0df',
    'v02_view': 'ac01be903348c8ee4d78d587e65c58d74d07d480bc0421fa3c358e79c66241df',
    'v02_plugin': '7e6cdea1ff8345f7d8b6bb7588b1a58c9102fc8065ce42f407cb23d86d47f7df',
    'rc4_plugin': '2ebd073415907ba43f11af2ab1e211d1e825fe7765abfe93f2b1a8176f44de24',
}
V02_ACL = 'dbf929c6b8fa3f76f5ac4b82adb58828cf6ec70ab3421aeedebea92cc63eef41'
RC3_SAMPLER = 'f817b1c9dc34d0767372355091f6ae02195a2941429c66b57245c7898cc0ca3c'
RC3_VIEW = '9517214620c0dd6bf819ee24c1975314f36701c1808630762b98472e5828b827'


class UpgradeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix='uulink-upgrade-')
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.package = self.root / 'package'
        self.commands = self.root / 'bin'
        self.commands.mkdir()
        self.events = self.root / 'service-events'
        self.events.touch()
        for name, (source, target) in FILES.items():
            packaged = self.package / source
            packaged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(AGENT / source, packaged)
            installed = self.root / target
            installed.parent.mkdir(parents=True, exist_ok=True)
            if name not in ('menu', 'view'):
                shutil.copy2(packaged, installed)
        self.assertEqual(self.actual_hash('acl'), V02_ACL)
        for path in ('etc/openwrt_release', 'usr/lib/rpcd/ucode.so', 'www/cgi-bin/luci'):
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()
        (self.root / 'root').mkdir()
        (self.root / 'tmp/luci-modulecache').mkdir(parents=True)
        self.make_command('id', 'echo 0')
        self.make_command('ucode', 'exit 0')
        self.make_command('ubus', '''case "$*" in
            list) echo uulink ;;
            'call mu300dash status') echo '{}' ;;
            *) echo '{}' ;;
        esac''')
        self.make_command('sleep', 'exit 0')
        self.make_command('fixture-service', 'printf "%s:%s\\n" "$1" "$2" >> "$FIXTURE_EVENTS"')
        fake_hashes = repr(OLD_HASHES)
        self.make_command('sha256sum', f'''python3 - "$1" <<'PY'
import hashlib, pathlib, sys
path = pathlib.Path(sys.argv[1])
payload = path.read_bytes()
old = {fake_hashes}
marker = payload.decode('ascii') if payload.startswith(b'fixture:') else ''
key = marker.removeprefix('fixture:').strip()
digest = old.get(key, hashlib.sha256(payload).hexdigest())
print(digest, path)
PY''')
        script = (AGENT / 'upgrade.sh').read_text()
        script = script.replace('/etc/init.d/uulink restart', 'fixture-service uulink restart')
        script = script.replace('/etc/init.d/rpcd restart', 'fixture-service rpcd restart')
        start = script.index('agent_ready() {')
        end = script.index('\n}\n\nwait_agent_ready()', start) + 2
        script = script[:start] + 'agent_ready() { [ "$FIXTURE_READY" = yes ]; }' + script[end:]
        script = script.replace('/etc/init.d/uulink status', 'fixture-service uulink status')
        for prefix in ('/etc', '/usr', '/www', '/root', '/tmp'):
            script = re.sub(r'(?<!files)' + re.escape(prefix) + r'(?=/)', str(self.root) + prefix, script)
        (self.package / 'upgrade.sh').write_text(script)

    def make_command(self, name, body):
        path = self.commands / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def actual_hash(self, name):
        return hashlib.sha256((self.package / FILES[name][0]).read_bytes()).hexdigest()

    def installed(self, name):
        return self.root / FILES[name][1]

    def marker(self, name, version):
        self.installed(name).write_text('fixture:' + version + '\n')

    def old_v01(self, variant='v01'):
        for name in ('menu', 'view'):
            self.installed(name).unlink(missing_ok=True)
        self.marker('plugin', variant + '_plugin')
        self.marker('acl', variant + '_acl')
        self.marker('sampler', 'v01_sampler')

    def old_v02(self, variant='v02'):
        self.marker('sampler', variant + '_sampler')
        self.marker('plugin', 'v02_plugin')
        shutil.copy2(self.package / FILES['menu'][0], self.installed('menu'))
        self.marker('view', 'v02_view')

    def old_rc(self, plugin='v02_plugin'):
        self.current()
        self.assertEqual(self.actual_hash('sampler'), RC3_SAMPLER)
        self.assertEqual(self.actual_hash('view'), RC3_VIEW)
        self.marker('plugin', plugin)

    def current(self):
        for name in ('sampler', 'menu', 'view'):
            shutil.copy2(self.package / FILES[name][0], self.installed(name))

    def run_upgrade(self, ready='yes'):
        return subprocess.run(
            ['/bin/sh', str(self.package / 'upgrade.sh')],
            env={**os.environ, 'PATH': f'{self.commands}:{os.environ["PATH"]}',
                 'FIXTURE_EVENTS': str(self.events), 'FIXTURE_READY': ready},
            capture_output=True, text=True, timeout=20,
        )

    def backed_up(self):
        return list((self.root / 'root').glob('uulink-upgrade.*'))

    def test_published_v02_and_confirmed_private_variants_upgrade_sampler_view_and_plugin(self):
        for variant in ('v02', 'u30air', 'f50'):
            with self.subTest(variant=variant):
                self.old_v02(variant)
                self.events.write_text('')
                caches = [self.root / 'tmp/luci-indexcache', self.root / 'tmp/luci-indexcache.old',
                          self.root / 'tmp/luci-modulecache/view.js']
                for cache in caches:
                    cache.write_text('stale')
                result = self.run_upgrade()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.installed('sampler').read_bytes(), (self.package / FILES['sampler'][0]).read_bytes())
                self.assertEqual(self.installed('view').read_bytes(), (self.package / FILES['view'][0]).read_bytes())
                self.assertEqual(self.installed('plugin').read_bytes(), (self.package / FILES['plugin'][0]).read_bytes())
                self.assertEqual(self.installed('acl').read_bytes(), (self.package / FILES['acl'][0]).read_bytes())
                self.assertEqual(self.events.read_text(), 'uulink:restart\nrpcd:restart\n')
                backup = self.backed_up()[-1]
                self.assertEqual((backup / 'index.js').read_text(), 'fixture:v02_view\n')
                self.assertEqual((backup / 'uulink.uc').read_text(), 'fixture:v02_plugin\n')
                self.assertFalse((backup / 'uulink-agent.json').exists())
                self.assertTrue(all(not cache.exists() for cache in caches))

    def test_v01_and_snapshot_only_upgrade_adds_ui_and_updates_core(self):
        for variant in ('v01', 'snapshot'):
            with self.subTest(variant=variant):
                self.old_v01(variant)
                self.events.write_text('')
                result = self.run_upgrade()
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in ('sampler', 'plugin', 'acl', 'menu', 'view'):
                    self.assertEqual(self.installed(name).read_bytes(), (self.package / FILES[name][0]).read_bytes())
                self.assertEqual(self.events.read_text(), 'uulink:restart\nrpcd:restart\n')

    def test_known_v02_failure_restores_old_view_sampler_and_plugin(self):
        self.old_v02()
        before = {name: self.installed(name).read_bytes() for name in ('sampler', 'plugin', 'acl', 'menu', 'view')}
        result = self.run_upgrade(ready='no')
        self.assertNotEqual(result.returncode, 0)
        for name, payload in before.items():
            self.assertEqual(self.installed(name).read_bytes(), payload, name)
        self.assertEqual(self.events.read_text(),
                         'uulink:restart\nrpcd:restart\nuulink:status\nuulink:restart\nrpcd:restart\n')

    def test_known_release_candidates_upgrade_only_plugin(self):
        for plugin in ('v02_plugin', 'rc4_plugin'):
            with self.subTest(plugin=plugin):
                self.old_rc(plugin)
                self.events.write_text('')
                previous_backups = set(self.backed_up())
                kept = {name: self.installed(name) for name in ('init', 'sampler', 'acl', 'menu', 'view')}
                for path in kept.values():
                    os.utime(path, (1700000000, 1700000000))
                result = self.run_upgrade()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.installed('plugin').read_bytes(), (self.package / FILES['plugin'][0]).read_bytes())
                for name, path in kept.items():
                    self.assertEqual(path.read_bytes(), (self.package / FILES[name][0]).read_bytes())
                    self.assertEqual(path.stat().st_mtime, 1700000000)
                self.assertEqual(self.events.read_text(), 'rpcd:restart\n')
                backup, = set(self.backed_up()) - previous_backups
                self.assertEqual([path.name for path in backup.iterdir()], ['uulink.uc'])
                self.assertEqual((backup / 'uulink.uc').read_text(), f'fixture:{plugin}\n')

    def test_known_release_candidate_failure_restores_plugin_and_restarts_only_rpcd(self):
        for plugin in ('v02_plugin', 'rc4_plugin'):
            with self.subTest(plugin=plugin):
                self.old_rc(plugin)
                self.events.write_text('')
                before = {name: self.installed(name).read_bytes() for name in FILES}
                result = self.run_upgrade(ready='no')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('previous files restored', result.stderr)
                for name, payload in before.items():
                    self.assertEqual(self.installed(name).read_bytes(), payload, name)
                self.assertEqual(self.events.read_text(), 'rpcd:restart\nuulink:status\nrpcd:restart\n')

    def test_v01_failure_removes_added_ui_and_restores_old_core(self):
        self.old_v01()
        before = {name: self.installed(name).read_bytes() for name in ('sampler', 'plugin', 'acl')}
        result = self.run_upgrade(ready='no')
        self.assertNotEqual(result.returncode, 0)
        for name, payload in before.items():
            self.assertEqual(self.installed(name).read_bytes(), payload, name)
        self.assertFalse(self.installed('menu').exists())
        self.assertFalse(self.installed('view').exists())
        self.assertEqual(self.events.read_text(),
                         'uulink:restart\nrpcd:restart\nuulink:status\nuulink:restart\nrpcd:restart\n')

    def test_current_version_is_idempotent(self):
        self.current()
        result = self.run_upgrade()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already up to date', result.stdout)
        self.assertEqual(self.events.read_text(), '')
        self.assertEqual(self.backed_up(), [])

    def test_unknown_and_mixed_versions_are_rejected_without_changes(self):
        cases = [
            lambda: (self.old_v02(), self.marker('sampler', 'unknown')),
            lambda: (self.old_v02(), self.marker('view', 'unknown')),
            lambda: (self.old_v02(), self.marker('plugin', 'v01_plugin')),
            lambda: (self.old_v02(), self.installed('view').unlink()),
            lambda: self.old_v01(),
            lambda: (self.old_rc(), self.marker('view', 'v02_view')),
            lambda: (self.old_rc(), self.marker('sampler', 'v02_sampler')),
            lambda: (self.old_rc('rc4_plugin'), self.marker('view', 'v02_view')),
            lambda: (self.old_v02(), self.marker('plugin', 'rc4_plugin')),
        ]
        for index, prepare in enumerate(cases):
            with self.subTest(case=index):
                for name in ('sampler', 'plugin', 'acl', 'menu', 'view'):
                    file = self.installed(name)
                    if file.exists():
                        file.unlink()
                    if name in ('sampler', 'plugin', 'acl'):
                        shutil.copy2(self.package / FILES[name][0], file)
                prepare()
                if index == 4:
                    shutil.copy2(self.package / FILES['menu'][0], self.installed('menu'))
                    self.marker('view', 'v02_view')
                before = {name: self.installed(name).read_bytes() if self.installed(name).exists() else None
                          for name in ('sampler', 'plugin', 'acl', 'menu', 'view')}
                self.events.write_text('')
                backups = len(self.backed_up())
                result = self.run_upgrade()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                after = {name: self.installed(name).read_bytes() if self.installed(name).exists() else None
                         for name in before}
                self.assertEqual(after, before)
                self.assertEqual(self.events.read_text(), '')
                self.assertEqual(len(self.backed_up()), backups)


if __name__ == '__main__':
    unittest.main()
